from datetime import datetime
from urllib.parse import urlencode

from csp.decorators import csp_update
from django.conf import settings
from django.http import (
    HttpResponse,
    HttpResponseRedirect,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, TemplateView
from requests import HTTPError

from waffle.mixins import WaffleFlagMixin

from dataworkspace.apps.core.utils import (
    USER_SCHEMA_STEM,
    db_role_schema_suffix_for_user,
    get_s3_prefix,
)
from dataworkspace.apps.your_files.forms import CreateTableForm
from dataworkspace.apps.your_files.utils import (
    copy_file_to_uploads_bucket,
    get_dataflow_dag_status,
    get_s3_csv_column_types,
    clean_db_identifier,
    trigger_dataflow_dag,
)


def file_browser_html_view(request):
    return (
        file_browser_html_GET(request)
        if request.method == 'GET'
        else HttpResponse(status=405)
    )


@csp_update(
    CONNECT_SRC=[settings.APPLICATION_ROOT_DOMAIN, "https://s3.eu-west-2.amazonaws.com"]
)
def file_browser_html_GET(request):
    prefix = get_s3_prefix(str(request.user.profile.sso_id))

    return render(
        request,
        'your_files/files.html',
        {
            'prefix': prefix,
            'bucket': settings.NOTEBOOKS_BUCKET,
            'YOUR_FILES_CREATE_TABLE_FLAG': settings.YOUR_FILES_CREATE_TABLE_FLAG,
        },
        status=200,
    )


class CreateTableView(WaffleFlagMixin, FormView):
    template_name = 'your_files/create-table.html'
    waffle_flag = settings.YOUR_FILES_CREATE_TABLE_FLAG
    form_class = CreateTableForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['path'] = self.request.GET['path']
        context['filename'] = context['path'].split('/')[-1]
        return context

    def get(self, request, *args, **kwargs):
        if 'path' not in self.request.GET:
            return HttpResponseBadRequest(
                "Expected a `path` parameter for the CSV file"
            )
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        path = form.cleaned_data['path']
        schema = (
            f'{USER_SCHEMA_STEM}{db_role_schema_suffix_for_user(self.request.user)}'
        )
        table_name = clean_db_identifier(path)
        column_definitions = get_s3_csv_column_types(path)
        import_path = settings.DATAFLOW_IMPORTS_BUCKET_ROOT + '/' + path
        copy_file_to_uploads_bucket(path, import_path)
        dag_run_id = f'{schema}-{table_name}-{datetime.now().isoformat()}'
        try:
            response = trigger_dataflow_dag(
                import_path, schema, table_name, column_definitions, dag_run_id
            )
        except HTTPError:
            return self.form_invalid(form)
        params = {
            'filename': path.split('/')[-1],
            'schema': schema,
            'table_name': table_name,
            'execution_date': response['execution_date'],
        }
        return HttpResponseRedirect(
            f'{reverse("your-files:create-table-validating")}?{urlencode(params)}'
        )

    def form_invalid(self, form):
        filename = form.data['path'].split('/')[-1]
        return HttpResponseRedirect(
            f'{reverse("your-files:create-table-failed")}?filename={filename}'
        )


class BaseCreateTableTemplateView(WaffleFlagMixin, TemplateView):
    waffle_flag = settings.YOUR_FILES_CREATE_TABLE_FLAG
    required_parameters = [
        'filename',
        'schema',
        'table_name',
        'execution_date',
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {param: self.request.GET.get(param) for param in self.required_parameters}
        )
        return context

    def get(self, request, *args, **kwargs):
        for param in self.required_parameters:
            if param not in self.request.GET:
                return HttpResponseBadRequest(
                    f'Expected a `{param}` parameter for the CSV file'
                )
        return super().get(request, *args, **kwargs)


class CreateTableValidatingView(BaseCreateTableTemplateView):
    template_name = 'your_files/create-table-validating.html'


class CreateTableIngestingView(BaseCreateTableTemplateView):
    template_name = 'your_files/create-table-ingesting.html'


class CreateTableSuccessView(BaseCreateTableTemplateView):
    template_name = 'your_files/create-table-success.html'


class CreateTableFailedView(WaffleFlagMixin, TemplateView):
    waffle_flag = settings.YOUR_FILES_CREATE_TABLE_FLAG
    template_name = 'your_files/create-table-failed.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filename'] = self.request.GET['filename']
        return context

    def get(self, request, *args, **kwargs):
        if 'filename' not in self.request.GET:
            return HttpResponseBadRequest(
                "Expected a `filename` parameter for the CSV file"
            )
        return super().get(request, *args, **kwargs)


class CreateTableDAGStatusView(View):
    """
    Check on the status of a DAG that has been run via the create table flow.

    Airflow 1 requires calling with the execution date which is not ideal. Once
    we have upgraded to Airflow 2 we can update this to call with the unique dag run id.

    Airflow 2 will also return more info, including the config we called the API with
    to trigger the DAG. Once we have this available we can then check if the file
    path in the response matches the s3 path prefix for the current user - as an extra
    step to check the current user actually created this dag run themselves.
    """

    def get(self, request, execution_date):
        try:
            return JsonResponse(get_dataflow_dag_status(execution_date))
        except HTTPError as e:
            return JsonResponse({}, status=e.response.status_code)
