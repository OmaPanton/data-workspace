import datetime
import hashlib
import json
import logging
import urllib.parse
import re

import gevent
import requests
from psycopg2 import connect, sql

from django.conf import settings
from django.db.models import Q

from dataworkspace.apps.applications.spawner import (
    get_spawner,
    stop,
    _fargate_task_describe,
)
from dataworkspace.apps.applications.models import (
    ApplicationInstance,
    ApplicationInstanceDbUsers,
    ApplicationTemplate,
)
from dataworkspace.apps.core.models import Database
from dataworkspace.apps.core.utils import database_dsn
from dataworkspace.cel import celery_app

logger = logging.getLogger('app')


def application_template_and_data_from_host(public_host):
    # Visualisations are matched by host_exact, and tools by host_pattern. Potentially down
    # the road the matching may need to be general, but the current use case requires a
    # single URL per visualisation, but a group of URLs for a tool (i.e. to extract the owner ID),
    # and this way uses database index(es) over the expected longer list of visualisations

    # To utilise a database index if we end up with a lot of visualisations
    matching_visualisation = list(
        ApplicationTemplate.objects.filter(application_type='VISUALISATION', host_exact=public_host)
    )
    matching_templates = matching_visualisation or ApplicationTemplate.objects.filter(application_type='TOOL')

    def public_host_pattern(application_template):
        # Historically didn't support standard named regex but used our own
        # format, e.g. '<customfield>-<user>'. Once all usage of this format
        # is removed from production, this function can be removed and just
        # use application_template.host_pattern
        if '?P<' in application_template.host_pattern:
            return application_template.host_pattern

        return '^' + re.sub('<(.+?)>', '(?P<\\1>.*?)', application_template.host_pattern) + '$'

    # ... and then match on pattern/extract data
    matching = [
        (application_template, host_data.groupdict())
        for application_template in matching_templates
        for host_data in [re.match(public_host_pattern(application_template), public_host)]
        if host_data
    ]
    if not matching:
        raise ApplicationTemplate.DoesNotExist()
    if len(matching) > 1:
        raise Exception('Too many ApplicatinTemplate matching host')

    return matching[0]


def api_application_dict(application_instance):
    spawner_state = get_spawner(application_instance.application_template.spawner).state(
        application_instance.spawner_application_template_options,
        application_instance.created_date.replace(tzinfo=None),
        application_instance.spawner_application_instance_id,
        application_instance.public_host,
    )

    # Only pass through the database state if the spawner is running,
    # Otherwise, we are in an error condition, and so return the spawner
    # state, so the client (i.e. the proxy) knows to take action
    api_state = application_instance.state if spawner_state == 'RUNNING' else spawner_state

    sso_id_hex = hashlib.sha256(str(application_instance.owner.profile.sso_id).encode('utf-8')).hexdigest()
    sso_id_hex_short = sso_id_hex[:8]

    return {
        'proxy_url': application_instance.proxy_url,
        'state': api_state,
        'user': sso_id_hex_short,
    }


def get_api_visible_application_instance_by_public_host(public_host):
    # From the point of view of the API, /public_host/<host-name> is a single
    # spawning or running application, and if it's not spawning or running
    # it doesn't exist. 'STOPPING' an application is DELETEing it. This may
    # need to be changed in later versions for richer behaviour.
    return ApplicationInstance.objects.get(public_host=public_host, state__in=['RUNNING', 'SPAWNING'])


def application_api_is_allowed(request, public_host):
    application_template, host_data = application_template_and_data_from_host(public_host)

    request_sso_id_hex = hashlib.sha256(str(request.user.profile.sso_id).encode('utf-8')).hexdigest()

    def is_tool_and_correct_user_and_allowed_to_start():
        return (
            application_template.application_type == 'TOOL'
            and host_data['user'] == request_sso_id_hex[:8]
            and request.user.has_perm('applications.start_all_applications')
        )

    def is_visualisation_and_requires_authentication():
        return (
            application_template.application_type == 'VISUALISATION'
            and application_template.user_access_type == 'REQUIRES_AUTHENTICATION'
        )

    def is_visualisation_and_requires_authorisation_and_has_authorisation():
        return (
            application_template.application_type == 'VISUALISATION'
            and application_template.user_access_type == 'REQUIRES_AUTHORIZATION'
            and request.user.applicationtemplateuserpermission_set.filter(
                application_template=application_template
            ).exists()
        )

    return (
        is_tool_and_correct_user_and_allowed_to_start()
        or is_visualisation_and_requires_authentication()
        or is_visualisation_and_requires_authorisation_and_has_authorisation()
    )


def stop_spawner_and_application(application_instance):
    stop.delay(application_instance.spawner, application_instance.id)
    set_application_stopped(application_instance)


def set_application_stopped(application_instance):
    application_instance.state = 'STOPPED'
    application_instance.single_running_or_spawning_integrity = str(application_instance.id)
    application_instance.save(update_fields=['state', 'single_running_or_spawning_integrity'])


def application_instance_max_cpu(application_instance):
    # If we don't have the proxy url yet, we can't have any metrics yet.
    # This is expected and should not be shown as an error
    if application_instance.proxy_url is None:
        raise ValueError('Unknown')

    instance = urllib.parse.urlsplit(application_instance.proxy_url).hostname + ':8889'
    url = f'https://{settings.PROMETHEUS_DOMAIN}/api/v1/query'
    params = {'query': f'increase(precpu_stats__cpu_usage__total_usage{{instance="{instance}"}}[30s])[2h:30s]'}
    try:
        response = requests.get(url, params)
    except requests.RequestException:
        raise ValueError('Error connecting to metrics server')

    response_dict = response.json()
    if response_dict['status'] != 'success':
        raise ValueError(f'Metrics server return value is {response_dict["status"]}')

    try:
        values = response_dict['data']['result'][0]['values']
    except (IndexError, KeyError):
        # The server not having metrics yet should not be reported as an error
        raise ValueError(f'Unknown')

    max_cpu = 0.0
    ts_at_max = 0
    for ts, cpu in values:
        cpu_float = float(cpu) / (1_000_000_000 * 30) * 100
        if cpu_float >= max_cpu:
            max_cpu = cpu_float
            ts_at_max = ts

    return max_cpu, ts_at_max


@celery_app.task()
def kill_idle_fargate():
    logger.info('kill_idle_fargate: Start')

    two_hours_ago = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=-2)
    instances = ApplicationInstance.objects.filter(
        spawner='FARGATE', state__in=['RUNNING', 'SPAWNING'], created_date__lt=two_hours_ago,
    )

    for instance in instances:
        if instance.state == 'SPAWNING':
            stop_spawner_and_application(instance)
            continue

        logger.info('kill_idle_fargate: Attempting to find CPU usage of %s', instance)
        try:
            max_cpu, _ = application_instance_max_cpu(instance)
        except Exception:
            logger.exception('kill_idle_fargate: Unable to find CPU usage for %s', instance)
            continue

        logger.info('kill_idle_fargate: CPU usage for %s is %s', instance, max_cpu)

        if max_cpu >= 1.0:
            continue

        try:
            stop_spawner_and_application(instance)
        except Exception:
            logger.exception('kill_idle_fargate: Unable to stop %s', instance)

        logger.info('kill_idle_fargate: Stopped application %s', instance)

    logger.info('kill_idle_fargate: End')


@celery_app.task()
def populate_created_stopped_fargate():
    logger.info('populate_created_stopped_fargate: Start')

    # This is used to populate spawner_created_at and spawner_stopped_at for
    # Fargate containers in two case:
    #
    # - For any that failed to populate spawner_created_at and
    #   spawner_stopped_at. This is possible since they are populated
    #   asynchronously, and although they retry on failure, it's not perfect
    #   if the Django instance went down at that moment
    #
    # - For those that existed before spawner_created_at, spawner_stopped_at
    #   were added. Unfortunately it appears that tasks are only stored for
    #   about 15 hours after they stop
    #   https://github.com/aws/amazon-ecs-agent/issues/368 so this is only
    #   of limited use
    #
    # We go back ~2 days of applications out of a bit of hope that more tasks
    # are stored. We also do an hour at a time to leverage the index on
    # created_date and just in case this is ever used for high numbers of
    # applications. We deliberately don't add an indexes for this case since
    # it's deemed not worth slowing inserts or using more disk space for this
    # non performance critical background task

    # Ensure we don't have a moving target of "now" during processing
    now = datetime.datetime.now(datetime.timezone.utc)

    for hours in range(0, 48):
        start_of_range = now + datetime.timedelta(hours=-hours - 1)
        end_of_range = now + datetime.timedelta(hours=-hours)
        instances = ApplicationInstance.objects.filter(
            Q(spawner='FARGATE', created_date__gte=start_of_range, created_date__lt=end_of_range,)
            & (Q(spawner_created_at__isnull=True) | Q(spawner_stopped_at__isnull=True))
        ).order_by('-created_date')

        for instance in instances:
            logger.info('populate_created_stopped_fargate checking: %s', instance)

            try:
                options = json.loads(instance.spawner_application_template_options)
                cluster_name = options['CLUSTER_NAME']
                task_arn = json.loads(instance.spawner_application_instance_id)['task_arn']
            except (ValueError, KeyError):
                continue

            # To not bombard the ECS API
            gevent.sleep(0.1)
            try:
                task = _fargate_task_describe(cluster_name, task_arn)
            except Exception:
                logger.exception('populate_created_stopped_fargate %s', instance)
                gevent.sleep(10)
                continue

            if not task:
                logger.info(
                    'populate_created_stopped_fargate no task found %s %s', instance, task_arn,
                )
                continue

            update_fields = []
            if 'createdAt' in task and instance.spawner_created_at is None:
                instance.spawner_created_at = task['createdAt']
                update_fields.append('spawner_created_at')

            if 'stoppedAt' in task and instance.spawner_stopped_at is None:
                instance.spawner_stopped_at = task['stoppedAt']
                update_fields.append('spawner_stopped_at')

            if update_fields:
                logger.info(
                    'populate_created_stopped_fargate saving: %s %s', instance, update_fields,
                )
                instance.save(update_fields=update_fields)

    logger.info('populate_created_stopped_fargate: End')


@celery_app.task()
def delete_unused_datasets_users():
    logger.info('delete_unused_datasets_users: Start')

    for memorable_name, database_data in settings.DATABASES_DATA.items():
        database_obj = Database.objects.get(memorable_name=memorable_name)
        database_name = database_data['NAME']

        with connect(database_dsn(database_data)) as conn, conn.cursor() as cur:
            logger.info('delete_unused_datasets_users: finding database users')
            cur.execute(
                """
                SELECT usename FROM pg_catalog.pg_user
                WHERE valuntil != 'infinity' AND usename LIKE 'user_%'
                ORDER BY usename;
            """
            )
            usenames = [result[0] for result in cur.fetchall()]

            logger.info('delete_unused_datasets_users: finding schemas')
            cur.execute(
                """
                SELECT DISTINCT schemaname FROM pg_tables
                WHERE schemaname != 'pg_catalog' and schemaname != 'information_schema'
                ORDER BY schemaname;
            """
            )
            schemas = [result[0] for result in cur.fetchall()]

        logger.info('delete_unused_datasets_users: waiting in case they were just created')
        gevent.sleep(15)

        # We want to be able to delete db users created, but then _not_ associated with an
        # running application, such as those from a STOPPED application, but also from those
        # that were created but then the server went down before the application was created.
        in_use_usenames = set(
            ApplicationInstanceDbUsers.objects.filter(
                db=database_obj, db_username__in=usenames, application_instance__state__in=['RUNNING', 'SPAWNING'],
            ).values_list('db_username', flat=True)
        )
        not_in_use_usernames = [usename for usename in usenames if usename not in in_use_usenames]

        schema_revokes = [
            'REVOKE USAGE ON SCHEMA {} FROM {};',
            'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} FROM {};',
            'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} FROM {};',
            'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA {} FROM {};',
            'ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL PRIVILEGES ON TABLES FROM {}',
            'ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL PRIVILEGES ON SEQUENCES FROM {}',
            'ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL PRIVILEGES ON FUNCTIONS FROM {}',
        ]

        with connect(database_dsn(database_data)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                for usename in not_in_use_usernames:
                    try:
                        logger.info(
                            'delete_unused_datasets_users: revoking credentials for %s', usename,
                        )
                        cur.execute(
                            sql.SQL('REVOKE CONNECT ON DATABASE {} FROM {};').format(
                                sql.Identifier(database_name), sql.Identifier(usename)
                            )
                        )
                        cur.execute(
                            sql.SQL('REVOKE ALL PRIVILEGES ON DATABASE {} FROM {};').format(
                                sql.Identifier(database_name), sql.Identifier(usename)
                            )
                        )

                        for schema in schemas:
                            for schema_revoke in schema_revokes:
                                try:
                                    cur.execute(
                                        sql.SQL(schema_revoke).format(sql.Identifier(schema), sql.Identifier(usename),)
                                    )
                                except Exception:
                                    # This is likely to happen for private schemas where the current user
                                    # does not have revoke privileges. We carry on in a best effort
                                    # to remove the user
                                    logger.info(
                                        'delete_unused_datasets_users: Unable to %s %s %s',
                                        schema_revoke,
                                        schema,
                                        usename,
                                    )

                        logger.info('delete_unused_datasets_users: dropping user %s', usename)
                        cur.execute(sql.SQL('DROP USER {};').format(sql.Identifier(usename)))
                    except Exception:
                        logger.exception('delete_unused_datasets_users: Failed deleting %s', usename)
                    else:
                        logger.info(
                            'delete_unused_datasets_users: revoked credentials for and dropped %s', usename,
                        )

    logger.info('delete_unused_datasets_users: End')
