import json
import os
import functools
import operator
from django.utils.dateparse import parse_datetime
from django.http import HttpResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from api.pagination import CustomPagination
from django.db.models import Q

from api.utils.email import send_fcm
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.models import User
from oauth2_provider.models import AccessToken
from api.models import *
from api.utils.notifier import notify_password_reset_code
from api.utils import validators
from api.utils.utils import get_aware_datetime
from api.serializers import user_serializer, profile_serializer, shift_serializer, employee_serializer, other_serializer, payment_serializer
from api.serializers import favlist_serializer, venue_serializer, employer_serializer, auth_serializer, notification_serializer, clockin_serializer
from api.serializers import rating_serializer
from rest_framework_jwt.settings import api_settings

import api.utils.jwt
jwt_decode_handler = api_settings.JWT_DECODE_HANDLER
jwt_encode_handler = api_settings.JWT_ENCODE_HANDLER

from django.utils import timezone
import datetime
TODAY = datetime.datetime.now(tz=timezone.utc)

# from .utils import GeneralException
import logging
logger = logging.getLogger(__name__)
from api.utils.email import get_template_content

import cloudinary
import cloudinary.uploader
import cloudinary.api

class EmailView(APIView):
    permission_classes = [AllowAny]
    def get(self, request, slug):
        template = get_template_content(slug)
        return HttpResponse(template['html'])
        
class FMCView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        
        body_unicode = request.body.decode('utf-8')
        body = json.loads(body_unicode)

        if "message_slug" not in body:
            body["message_slug"] = "invite_to_shift"
            
        result = send_fcm(body["message_slug"], [body["registration_id"]], {
            "COMPANY": "Blizard Inc",
            "POSITION": "Server",
            "DATE": "Whenever you have time",
            "LINK": 'https://jobcore.co/talent/invite',
            "DATA": body["data"]
        })
        
        return Response(result, status=status.HTTP_200_OK)
        

class EmployeeBadgesView(APIView, CustomPagination):
    def put(self, request, employee_id = None):

        request.data['employee'] = employee_id
        serializer = other_serializer.EmployeeBadgeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
class EmployerUsersView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                user = User.objects.get(id=id)
            except User.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = UserGetSmallSerializer(user, many=False)
        else:
            users = User.objects.all()
            serializer = user_serializer.UserGetSmallSerializer(users, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

class PayrollPeriodView(APIView):
    def get(self, request, period_id=None):
        if period_id:
            try:
                period = PayrollPeriod.objects.get(id=period_id)
            except PayrollPeriod.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = payment_serializer.PayrollPeriodGetSerializer(period)
        else:
            periods = PayrollPeriod.objects.all()
            
            qStatus = request.GET.get('status')
            if qStatus:
                periods = periods.filter(status=qStatus)
            
            qEmployer = request.GET.get('employer')
            if qEmployer:
                periods = periods.filter(employer__id=qEmployer)
                
            serializer = payment_serializer.PayrollPeriodGetSerializer(periods, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)
        
class GeneratePeriodsView(APIView):
    def get(self, request, employer_id=None):

        if employer_id:
            try:
                employer = Employer.objects.get(id=employer_id)
            except Employer.DoesNotExist:
                return Response(validators.error_object('Employer found.'), status=status.HTTP_404_NOT_FOUND)
            periods = payment_serializer.generate_period_periods(employer)
        
        else:
            employers = Employer.objects.all()
            periods = []
            for employer in employers:
                periods = periods + payment_serializer.generate_period_periods(employer)
                
        serializer = payment_serializer.PayrollPeriodGetSerializer(periods, many=True)
        
        return Response(serializer.data, status=status.HTTP_200_OK)
        
class AdminEmployerView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                employer = Employer.objects.get(id=id)
            except Employer.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = employer_serializer.EmployerGetSerializer(employer, many=False)
        else:
            employers = Employer.objects.all()
            serializer = employer_serializer.EmployerGetSerializer(employers, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        try:
            employer = Employer.objects.get(id=id)
        except Employer.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = employer_serializer.EmployerSerializer(employer, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            employer = Employer.objects.get(id=id)
        except Employer.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        employer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)