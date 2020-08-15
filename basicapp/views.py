from basicapp.forms import PatientForm
from basicapp.models import Patient
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.generic import (TemplateView)


# Create your views here.


def patient_list(request):
    patients = Patient.objects.all()
    return render(request, 'patient_list.html', {'patients': patients})


def upload(request):
    context = {}
    if request.method == 'POST':
        form = PatientForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('/basicapp/patient_list/')

    else:
        form = PatientForm()
    return render(request, 'patient_form.html', {'form': form})


class AboutView(TemplateView):
    template_name = 'about.html'


class IndexView(TemplateView):
    template_name = 'index.html'
