from django.contrib.auth import get_user_model

from django.contrib.postgres.forms import SplitArrayField, SplitArrayWidget
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.forms import (
    Textarea,
    TextInput,
    ModelChoiceField,
    HiddenInput,
    CharField,
    CheckboxInput,
    BooleanField,
)

from dataworkspace.apps.applications.models import VisualisationApproval
from dataworkspace.apps.datasets.models import VisualisationCatalogueItem
from dataworkspace.forms import GOVUKDesignSystemModelForm


class _NiceEmailValidationModelChoiceField(ModelChoiceField):
    def clean(self, value):
        if value:
            EmailValidator(message=self.error_messages['invalid_email'])(value.lower())
        return super().clean(value.lower() if value else value)


class BulletListSplitArrayWidget(SplitArrayWidget):
    template_name = "partials/bullet_list_split_array_widget.html"

    def __init__(self, label, input_prefix, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label = label
        self.input_prefix = input_prefix

    def get_context(self, name, value, attrs=None):
        context = super().get_context(name, value, attrs)

        context['widget']['label'] = self.label

        for i, _ in enumerate(context['widget']['subwidgets']):
            context['widget']['subwidgets'][i]['label'] = f"{self.input_prefix} #{i+1}"
        return context


class DWSplitArrayField(SplitArrayField):
    def clean(self, value):
        # Remove any blank entries from the middle of the list, then pad the end with blank values. The parent class
        # errors if there are blank values in between two non-blank values, and we don't care about that. Just get
        # rid of them and collapse down.
        value = list(filter(lambda x: x, value))
        value.extend([''] * (self.size - len(value)))
        return super().clean(value)


class VisualisationsUICatalogueItemForm(GOVUKDesignSystemModelForm):
    enquiries_contact = _NiceEmailValidationModelChoiceField(
        queryset=get_user_model().objects.all(),
        to_field_name='email',
        widget=TextInput,
        required=False,
        error_messages={
            "invalid_email": "Enter a valid email address for the enquiries contact",
            "invalid_choice": "The enquiries contact must have previously visited Data Workspace",
        },
    )
    secondary_enquiries_contact = _NiceEmailValidationModelChoiceField(
        queryset=get_user_model().objects.all(),
        to_field_name='email',
        widget=TextInput,
        required=False,
        error_messages={
            "invalid_email": "Enter a valid email address for the secondary enquiries contact",
            "invalid_choice": "The secondary enquiries contact must have previously visited Data Workspace",
        },
    )
    information_asset_manager = _NiceEmailValidationModelChoiceField(
        queryset=get_user_model().objects.all(),
        to_field_name='email',
        widget=TextInput,
        required=False,
        error_messages={
            "invalid_email": "Enter a valid email address for the information asset manager",
            "invalid_choice": "The information asset manager must have previously visited Data Workspace",
        },
    )
    information_asset_owner = _NiceEmailValidationModelChoiceField(
        queryset=get_user_model().objects.all(),
        to_field_name='email',
        widget=TextInput,
        required=False,
        error_messages={
            "invalid_email": "Enter a valid email address for the information asset owner",
            "invalid_choice": "The information asset owner must have previously visited Data Workspace",
        },
    )
    user_access_type = BooleanField(
        label='Each user must be individually authorized to access the data',
        required=False,
        widget=CheckboxInput(check_test=lambda val: val == 'REQUIRES_AUTHORIZATION'),
    )
    eligibility_criteria = DWSplitArrayField(
        CharField(required=False),
        widget=BulletListSplitArrayWidget(
            label="Eligibility criteria",
            input_prefix="Eligibility criterion",
            widget=TextInput(attrs={"class": "govuk-input"}),
            size=5,
        ),
        required=False,
        size=5,
        remove_trailing_nulls=True,
        label="Eligibility criteria",
    )

    class Meta:
        model = VisualisationCatalogueItem
        fields = [
            'short_description',
            'description',
            'enquiries_contact',
            'secondary_enquiries_contact',
            'information_asset_manager',
            'information_asset_owner',
            'licence',
            'retention_policy',
            'personal_data',
            'restrictions_on_usage',
            'user_access_type',
            'eligibility_criteria',
        ]
        widgets = {"retention_policy": Textarea, "restrictions_on_usage": Textarea}

    def __init__(self, *args, **kwargs):
        kwargs['initial'] = kwargs.get("initial", {})
        super().__init__(*args, **kwargs)
        is_instance = 'instance' in kwargs and kwargs['instance']

        self.fields['short_description'].error_messages[
            'required'
        ] = "The visualisation must have a summary"

        self._email_fields = [
            'enquiries_contact',
            'secondary_enquiries_contact',
            'information_asset_manager',
            'information_asset_owner',
        ]

        # Set the form field data for email fields to the actual user email address - by default it's the User ID.
        for field in self._email_fields:
            if getattr(self.instance, field):
                self.initial[field] = getattr(self.instance, field).email

        self.fields['user_access_type'].initial = (
            kwargs['instance'].user_access_type == 'REQUIRES_AUTHORIZATION'
            if is_instance
            else True
        )

    def clean_user_access_type(self):
        return (
            'REQUIRES_AUTHORIZATION'
            if self.cleaned_data['user_access_type']
            else 'REQUIRES_AUTHENTICATION'
        )


class VisualisationApprovalForm(GOVUKDesignSystemModelForm):
    class Meta:
        model = VisualisationApproval
        fields = ['approved', 'visualisation', 'approver']
        widgets = {"visualisation": HiddenInput, "approver": HiddenInput}
        labels = {"approved": "I have reviewed this visualisation"}

    def __init__(self, *args, **kwargs):
        # If the visualisation has already been approved, we want to render a form that allows the user to unapprove it.
        if kwargs.get('instance') and kwargs.get('instance').approved:
            self._initial_approved = True
            self.Meta.widgets["approved"] = HiddenInput
            kwargs['initial']['approved'] = False
        else:
            self._initial_approved = False

        super().__init__(*args, **kwargs)

        if self._initial_approved:
            self.fields['approved'].required = False

    def clean_approved(self):
        if not self._initial_approved and not self.cleaned_data['approved']:
            raise ValidationError(
                "You must confirm that you have reviewed this visualisation"
            )
        return self.cleaned_data['approved']
