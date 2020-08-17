from django.contrib.auth import authenticate
from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.urls import reverse_lazy, reverse

from .forms import SignUpForm, UserForm
from .models import CustomUser
from django.views.generic import View, CreateView
from django.contrib.auth import views as auth_views
import pdb


# Create your views here.

class SignUpView(CreateView):
    template_name = 'register.html'
    form_class = SignUpForm
    success_url = reverse_lazy('login')


class LoginView(auth_views.LoginView):
    template_name = 'login.html'

    def get_success_url(self):
        email = self.request.POST.get('username')
        email = CustomUser.objects.get(email=email)

        if email.specialty == 'doctor':
            return reverse('index')
        else:
            return reverse('deepmodel:UploadModel')

