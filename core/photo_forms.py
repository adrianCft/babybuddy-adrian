from django import forms
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _


class MultiplePhotoInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiplePhotoField(forms.ImageField):
    widget = MultiplePhotoInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if len(files) > 8:
            raise forms.ValidationError(_("Upload up to 8 photos at a time."))
        result = []
        for upload in files:
            if upload.size > 10 * 1024 * 1024:
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
                required=False, label=_("Photos"),
                help_text=_("Select one or more photos (up to 8, 10 MB each)."),
                widget=MultiplePhotoInput(attrs={"accept": "image/*"}),
            )
        if self.instance.pk:
            self.fields["remove_photos"] = forms.ModelMultipleChoiceField(
                queryset=HealthPhoto.objects.filter(**{self.photo_owner: self.instance}),
                required=False, label=_("Photos to remove"),
                widget=forms.CheckboxSelectMultiple,
            )
        # Core forms use fieldsets; include attachment controls in that layout.
        if getattr(self, "fieldsets", None):
            self.fieldsets = list(self.fieldsets) + [{"fields": [
                name for name in ("photos", "remove_photos") if name in self.fields
            ]}]

    def save(self, commit=True):
        from core.models import HealthPhoto
        with transaction.atomic():
            instance = super().save(commit=commit)
            if commit:
                for photo in self.cleaned_data.get("remove_photos", []):
                    photo.delete()
                for upload in self.cleaned_data.get("photos", []):
                    HealthPhoto.objects.create(image=upload, **{self.photo_owner: instance})
        return instance
