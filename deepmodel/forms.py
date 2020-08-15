from django import forms
from .models import DeepModel


class SlicesForm(forms.Form):
    slice_num = forms.CharField()
    patient_id = forms.CharField()


class SlicesFormdl(forms.Form):
    slice_num = forms.CharField()
    patient_id = forms.CharField()


class DeepModelForm(forms.ModelForm):
    class Meta:
        model = DeepModel
        fields = ('model_file',)
