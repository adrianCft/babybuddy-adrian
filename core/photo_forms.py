from django import forms
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.urls import reverse

MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 10 * 1024 * 1024


class MultiplePhotoInput(forms.ClearableFileInput):
    allow_multiple_selected = True
    template_name = "core/widget_photo_uploads.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update(
            photo_limit=MAX_PHOTOS, photo_bytes=MAX_PHOTO_BYTES, reselect=bool(value)
        )
        return context


class PhotoRemovalSelect(forms.CheckboxSelectMultiple):
    template_name = "core/widget_photo_remove.html"

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex, attrs
        )
        if value:
            option["photo_url"] = reverse("core:health-photo", args=[value.instance.pk])
        option["attrs"]["class"] = "form-check-input"
        return option


class MultiplePhotoField(forms.ImageField):
    widget = MultiplePhotoInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if len(files) > MAX_PHOTOS:
            raise forms.ValidationError(_("Upload up to 8 photos at a time."))
        result = []
        for upload in files:
            if upload.size > MAX_PHOTO_BYTES:
                raise forms.ValidationError(_("Each photo must be smaller than 10 MB."))
            result.append(super().clean(upload, initial))
        return result


class PhotoFormMixin:
    """Used by both the existing dose form and new health record forms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import HealthPhoto

        if settings.BABY_BUDDY["ALLOW_UPLOADS"]:
            self.fields["photos"] = MultiplePhotoField(
                required=False,
                label=_("Photos"),
                help_text=_("Select one or more photos (up to 8, 10 MB each)."),
                widget=MultiplePhotoInput(attrs={"accept": "image/*"}),
            )
        if self.instance.pk:
            self.fields["remove_photos"] = forms.ModelMultipleChoiceField(
                queryset=HealthPhoto.objects.filter(
                    **{self.photo_owner: self.instance}
                ),
                required=False,
                label=_("Saved photos"),
                help_text=_(
                    "Selected photos will only be removed when you save. Leave them unchecked to keep them."
                ),
                widget=PhotoRemovalSelect,
            )
        # Core forms use fieldsets; include attachment controls in that layout.
        if getattr(self, "fieldsets", None):
            photo_fields = [
                name for name in ("photos", "remove_photos") if name in self.fields
            ]
            self.fieldsets = list(self.fieldsets)
            if photo_fields:
                self.fieldsets.append(
                    {
                        "title": _("Photos"),
                        "fields": photo_fields,
                        "layout": "section",
                        "layout_attrs": {"photos": True},
                    }
                )

    def save(self, commit=True):
        from core.models import HealthPhoto

        with transaction.atomic():
            instance = super().save(commit=commit)
            if commit:
                for photo in self.cleaned_data.get("remove_photos", []):
                    photo.delete()
                for upload in self.cleaned_data.get("photos", []):
                    HealthPhoto.objects.create(
                        image=upload, **{self.photo_owner: instance}
                    )
        return instance
