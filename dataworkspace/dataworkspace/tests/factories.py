import uuid
from datetime import datetime

import factory.fuzzy

from django.contrib.auth import get_user_model


class UserProfileFactory(factory.django.DjangoModelFactory):
    sso_id = '7f93c2c7-bc32-43f3-87dc-40d0b8fb2cd2'

    class Meta:
        model = 'accounts.Profile'


class UserFactory(factory.django.DjangoModelFactory):
    username = 'test.user@example.com'
    password = '12345'

    class Meta:
        model = get_user_model()


class DatabaseFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda _: uuid.uuid4())
    memorable_name = 'test_external_db'

    class Meta:
        model = 'core.Database'
        django_get_or_create = ('memorable_name',)


class DataGroupingFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda _: uuid.uuid4())
    name = factory.fuzzy.FuzzyText()
    slug = factory.fuzzy.FuzzyText(length=10)

    class Meta:
        model = 'datasets.DataGrouping'


class DataSetFactory(factory.django.DjangoModelFactory):
    volume = 1
    grouping = factory.SubFactory(DataGroupingFactory)
    name = factory.fuzzy.FuzzyText()
    slug = factory.fuzzy.FuzzyText(length=10)
    published = True

    class Meta:
        model = 'datasets.DataSet'


class SourceLinkFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda _: uuid.uuid4())
    dataset = factory.SubFactory(DataSetFactory)
    name = factory.fuzzy.FuzzyText()
    format = factory.fuzzy.FuzzyText(length=5)
    frequency = factory.fuzzy.FuzzyText(length=5)
    url = 'http://example.com'

    class Meta:
        model = 'datasets.SourceLink'


class SourceTableFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda _: uuid.uuid4())
    dataset = factory.SubFactory(DataSetFactory)
    database = factory.SubFactory(DatabaseFactory)

    class Meta:
        model = 'datasets.SourceTable'


class SourceViewFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda _: uuid.uuid4())
    dataset = factory.SubFactory(DataSetFactory)
    database = factory.SubFactory(DatabaseFactory)

    class Meta:
        model = 'datasets.SourceView'


class CustomDatasetQueryFactory(factory.django.DjangoModelFactory):
    name = factory.fuzzy.FuzzyText()
    dataset = factory.SubFactory(DataSetFactory)
    database = factory.SubFactory(DatabaseFactory)
    frequency = 1

    class Meta:
        model = 'datasets.CustomDatasetQuery'


class ReferenceDatasetFactory(factory.django.DjangoModelFactory):
    group = factory.SubFactory(DataGroupingFactory)
    name = factory.fuzzy.FuzzyText()
    slug = factory.fuzzy.FuzzyText(length=10)
    published = True
    schema_version = factory.Sequence(lambda n: n)
    table_name = factory.fuzzy.FuzzyText(length=20)

    class Meta:
        model = 'datasets.ReferenceDataset'


class ReferenceDatasetFieldFactory(factory.django.DjangoModelFactory):
    reference_dataset = factory.SubFactory(ReferenceDatasetFactory)
    name = factory.fuzzy.FuzzyText()
    column_name = factory.fuzzy.FuzzyText(length=65)
    data_type = 1

    class Meta:
        model = 'datasets.ReferenceDatasetField'


class EventLogFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory(UserFactory)
    event_type = 1

    class Meta:
        model = 'eventlog.EventLog'


class ApplicationTemplateFactory(factory.django.DjangoModelFactory):
    name = 'Test Application'
    visible = True
    host_pattern = 'testapplication-<user>'
    nice_name = 'Test Application'
    spawner_time = int(datetime.timestamp(datetime.now()))

    class Meta:
        model = 'applications.ApplicationTemplate'
        django_get_or_create = ('name',)
