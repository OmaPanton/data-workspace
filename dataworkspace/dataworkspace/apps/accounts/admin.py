from django import forms
from django.contrib import admin
from django.contrib.admin.models import (
    LogEntry,
    CHANGE,
)
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import (
    UserAdmin,
)
from django.contrib.auth.models import (
    Permission,
)
from django.contrib.contenttypes.models import (
    ContentType,
)
from django.db import (
    transaction,
)
from django.forms.widgets import (
    CheckboxSelectMultiple,
)
from django.utils.encoding import (
    force_text,
)

from dataworkspace.apps.datasets.models import DataSet, DataSetUserPermission
from dataworkspace.apps.applications.models import ApplicationInstance


class AppUserCreationForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('email', 'first_name', 'last_name')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class AppUserEditForm(forms.ModelForm):
    can_start_all_applications = forms.BooleanField(
        label='Can start local tools',
        help_text='For JupyterLab, rStudio and pgAdmin',
        required=False,
    )
    can_access_appstream = forms.BooleanField(
        label='Can access AppStream',
        help_text='For SPSS and STATA',
        required=False,
    )
    authorized_datasets = forms.ModelMultipleChoiceField(
        label='Authorized datasets',
        required=False,
        widget=CheckboxSelectMultiple,
        queryset=None,
    )

    class Meta:
        model = get_user_model()
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs['instance']

        self.fields['can_start_all_applications'].initial = instance.user_permissions.filter(
            codename='start_all_applications',
            content_type=ContentType.objects.get_for_model(ApplicationInstance),
        ).exists()

        self.fields['can_access_appstream'].initial = instance.user_permissions.filter(
            codename='access_appstream',
            content_type=ContentType.objects.get_for_model(ApplicationInstance),
        ).exists()

        self.fields['authorized_datasets'].queryset = DataSet.objects.all().order_by('grouping__name', 'name', 'id')
        self.fields['authorized_datasets'].initial = DataSet.objects.filter(
            datasetuserpermission__user=instance,
        )


admin.site.unregister(get_user_model())


class LocalToolsFilter(admin.SimpleListFilter):
    title = 'Local tool access'
    parameter_name = 'can_start_tools'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Can start local tools'),
            ('no', 'Cannot start local tools'),
        )

    def queryset(self, request, queryset):
        perm = Permission.objects.get(
            codename='start_all_applications',
            content_type=ContentType.objects.get_for_model(ApplicationInstance),
        )
        if self.value() == 'yes':
            return queryset.filter(user_permissions=perm)
        if self.value() == 'no':
            return queryset.exclude(user_permissions=perm)
        return queryset


class AppStreamFilter(admin.SimpleListFilter):
    title = 'AppStream access'
    parameter_name = 'can_access_appstream'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Can access AppStream'),
            ('no', 'Cannot access AppStream'),
        )

    def queryset(self, request, queryset):
        perm = Permission.objects.get(
            codename='access_appstream',
            content_type=ContentType.objects.get_for_model(ApplicationInstance),
        )
        if self.value() == 'yes':
            return queryset.filter(user_permissions=perm)
        if self.value() == 'no':
            return queryset.exclude(user_permissions=perm)
        return queryset


class DatasetUserPermissionInline(admin.TabularInline):
    model = DataSetUserPermission
    extra = 0
    autocomplete_fields = ['dataset']


@admin.register(get_user_model())
class AppUserAdmin(UserAdmin):
    add_form_template = 'admin/change_form.html'
    add_form = AppUserCreationForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name',),
        }),
    )
    list_filter = (
        'is_staff',
        'is_superuser',
        'is_active',
        'groups',
        LocalToolsFilter,
        AppStreamFilter
    )
    form = AppUserEditForm
    fieldsets = [
        (None, {
            'fields': ['email', 'sso_id', 'first_name', 'last_name']
        }),
        ('Permissions', {
            'fields': [
                'can_start_all_applications',
                'can_access_appstream',
                'is_staff',
                'is_superuser',
            ]}),
    ]
    readonly_fields = ['sso_id']
    inlines = [
        DatasetUserPermissionInline,
    ]

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        content_type = ContentType.objects.get_for_model(obj).pk
        object_repr = force_text(obj)
        user_id = request.user.pk
        object_id = obj.pk

        obj.username = form.cleaned_data['email']

        def log_change(message):
            LogEntry.objects.log_action(
                user_id=user_id, content_type_id=content_type, object_id=object_id,
                object_repr=object_repr, action_flag=CHANGE, change_message=message,
            )

        start_all_applications_permission = Permission.objects.get(
            codename='start_all_applications',
            content_type=ContentType.objects.get_for_model(ApplicationInstance),
        )
        access_appstream_permission = Permission.objects.get(
            codename='access_appstream',
            content_type=ContentType.objects.get_for_model(ApplicationInstance),
        )

        if 'can_start_all_applications' in form.cleaned_data:
            if (
                    form.cleaned_data['can_start_all_applications'] and
                    start_all_applications_permission not in obj.user_permissions.all()
            ):
                obj.user_permissions.add(start_all_applications_permission)
                log_change('Added can_start_all_applications permission')
            elif start_all_applications_permission in obj.user_permissions.all():
                obj.user_permissions.remove(start_all_applications_permission)
                log_change('Removed can_start_all_applications permission')

        if 'can_access_appstream' in form.cleaned_data:
            if (
                    form.cleaned_data['can_access_appstream'] and
                    access_appstream_permission not in obj.user_permissions.all()
            ):
                obj.user_permissions.add(access_appstream_permission)
                log_change('Added can_access_appstream permission')
            elif access_appstream_permission in obj.user_permissions.all():
                obj.user_permissions.remove(access_appstream_permission)
                log_change('Removed can_access_appstream permission')

        super().save_model(request, obj, form, change)

    def sso_id(self, instance):
        return instance.profile.sso_id
