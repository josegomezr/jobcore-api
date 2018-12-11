import json
import os
import functools
import operator
from django.http import HttpResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from oauth2_provider.contrib.rest_framework import TokenHasReadWriteScope, TokenHasScope
from api.pagination import CustomPagination
from django.core.exceptions import ValidationError
from django.db.models import Q

from api.utils.email import send_fcm
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.models import User
from oauth2_provider.models import AccessToken
from api.models import *
from api.utils.notifier import notify_password_reset_code
from api.utils import validators
from api.serializers import user_serializer, profile_serializer, shift_serializer, employee_serializer, other_serializer, favlist_serializer, venue_serializer, employer_serializer, auth_serializer, notification_serializer, clockin_serializer
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

class ValidateEmailView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        token = request.GET.get('token')
        payload = jwt_decode_handler(token)
        try:
            user = User.objects.get(id=payload["user_id"])
            user.profile.status = ACTIVE #email validation completed
            user.profile.save()
        except User.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)
            
        template = get_template_content('email_validated')
        return HttpResponse(template['html'])

class PasswordView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        
        token = request.GET.get('token')
        data = jwt_decode_handler(token)
        try:
            user = User.objects.get(id=data['user_id'])
        except User.DoesNotExist:
            return Response({'error': 'Email not found on the database'}, status=status.HTTP_404_NOT_FOUND)

        payload = api.utils.jwt.jwt_payload_handler({
            "user_id": user.id
        })
        token = jwt_encode_handler(payload)

        template = get_template_content('reset_password_form', { "email": user.email, "token": token })
        return HttpResponse(template['html'])
        
    def post(self, request):
        email = request.data.get('email', None)
        if not email:
            return Response(validators.error_object('Email not found on the database'), status=status.HTTP_400_BAD_REQUEST)
            
        try:
            user = User.objects.get(email=email)
            serializer = auth_serializer.UserLoginSerializer(user)
        except User.DoesNotExist:
            return Response(validators.error_object('Email not found on the database'), status=status.HTTP_404_NOT_FOUND)

        notify_password_reset_code(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    def put(self, request):
        
        serializer = auth_serializer.ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserRegisterView(APIView):
    permission_classes = [AllowAny]
    #serializer_class = user_serializer.UserSerializer

    def post(self, request):
        serializer = auth_serializer.UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly, TokenHasReadWriteScope]

    def get(self, request, id):
        try:
            user = User.objects.get(id=id)
            serializer = user_serializer.UserGetSerializer(user)
        except User.DoesNotExist:
            return Response(validators.error_object('The user was not found'), status=status.HTTP_404_NOT_FOUND)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        try:
            user = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(validators.error_object('The user was not found'), status=status.HTTP_404_NOT_FOUND)

        serializer = user_serializer.UserSerializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, id):
        try:
            user = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(validators.error_object('The user was not found'), status=status.HTTP_404_NOT_FOUND)

        serializer = user_serializer.ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            if serializer.data.get("new_password"):
                # Check old password
                if not user.check_password(serializer.data.get("old_password")):
                    return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
                # Hash and save the password
                user.set_password(serializer.data.get("new_password"))
            user.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        permission_classes = [IsAuthenticated]

        try:
            user = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(validators.error_object('The user was not found'), status=status.HTTP_404_NOT_FOUND)

        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class EmployeeView(APIView, CustomPagination):
    def get(self, request, id=False):
        if (id):
            try:
                employee = Employee.objects.get(id=id)
            except Employee.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = employee_serializer.EmployeeGetSerializer(employee, many=False)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            employees = Employee.objects.all()
            
            qName = request.GET.get('full_name')
            if qName:
                search_args = []
                for term in qName.split():
                    for query in ('profile__user__first_name__istartswith', 'profile__user__last_name__istartswith'):
                        search_args.append(Q(**{query: term}))
                
                employees = employees.filter(functools.reduce(operator.or_, search_args))
            else:
                qFirst = request.GET.get('first_name')
                if qFirst:
                    employees = employees.filter(profile__user__first_name__contains=qFirst)
                    entities = []
    
                qLast = request.GET.get('last_name')
                if qLast:
                    employees = employees.filter(profile__user__last_name__contains=qLast)

            qPositions = request.GET.getlist('positions')
            if qPositions:
                employees = employees.filter(positions__id__in=qPositions)

            qBadges = request.GET.getlist('badges')
            if qBadges:
                employees = employees.filter(badges__id__in=qBadges)
            
            serializer = employee_serializer.EmployeeGetSmallSerializer(employees, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

    # there shoud be no POST because it is created on signup (registration)
    
    def delete(self, request, id):
        try:
            employee = Employee.objects.get(id=id)
        except Employee.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        employee.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
        
class EmployeeMeView(APIView, CustomPagination):
    def get(self, request):
        if request.user.profile.employee == None:
            raise PermissionDenied("You are not a talent, you can not update your employee profile")
            
        try:
            employee = Employee.objects.get(id=request.user.profile.employee.id)
        except Employee.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = employee_serializer.EmployeeGetSerializer(employee, many=False)
        return Response(serializer.data, status=status.HTTP_200_OK)
        

    def put(self, request):
        
        if request.user.profile.employee == None:
            raise PermissionDenied("You are not a talent, you can not update your employee profile")

        try:
            employee = Employee.objects.get(id=request.user.profile.employee.id)
        except Employee.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = employee_serializer.EmployeeSettingsSerializer(employee, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AvailabilityBlockView(APIView, CustomPagination):

    def get(self, request, employee_id=False):
            
        if employee_id == False and request.user.profile.employee == None:
            raise PermissionDenied("You are not allowed to update employee availability")
        
        if employee_id == False:
            employee_id = request.user.profile.employee.id
                
        unavailability_blocks = AvailabilityBlock.objects.all().filter(employee__id=employee_id)
        
        serializer = other_serializer.AvailabilityBlockSerializer(unavailability_blocks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, employee_id=None):
        if request.user.profile.employee == None:
            raise PermissionDenied("You are not allowed to update employee availability")
        
        request.data['employee'] = request.user.profile.employee.id
        serializer = other_serializer.AvailabilityBlockSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, block_id=None):
        
        if request.user.profile.employee == None:
            raise PermissionDenied("You are not allowed to update employee availability")
            
        try:
            block = AvailabilityBlock.objects.get(id=block_id, employee=request.user.profile.employee)
        except AvailabilityBlock.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)
        
        serializer = other_serializer.AvailabilityBlockSerializer(block, data=request.data, context={"request": request}, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    def delete(self, request, unavailability_id):
        try:
            unavailability_block = EmployeeWeekUnvailability.objects.get(id=unavailability_id)
        except EmployeeWeekUnvailability.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        unavailability_block.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class EmployeeApplicationsView(APIView, CustomPagination):
    def get(self, request, id=False):
        if (id):
            try:
                employee = Employee.objects.get(id=id)
            except Employee.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            applications = ShiftApplication.objects.all().filter(employer__id=employee.id).order_by('shift__starting_at')
            
            serializer = shift_serializer.ShiftApplicationSerializer(applications, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

class EmployeeMeApplicationsView(APIView, CustomPagination):
    def get(self, request, id=False):
        if request.user.profile.employee == None:
            raise PermissionDenied("You are not a talent, you can not update your employee profile")
            
        applications = ShiftApplication.objects.all().filter(employee__id=request.user.profile.employee.id).order_by('shift__starting_at')
        
        serializer = shift_serializer.ApplicantGetSerializer(applications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ApplicantsView(APIView, CustomPagination):

    def get(self, request, application_id=False):
        
        if(application_id):
            try:
                application = ShiftApplication.objects.get(id=application_id)
            except ShiftApplication.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = shift_serializer.ApplicantGetSmallSerializer(application, many=False)
        else:
            applications = ShiftApplication.objects.select_related('employee','shift').all()
            # data = [applicant.id for applicant in applications]
            serializer = shift_serializer.ApplicantGetSmallSerializer(applications, many=True)
        
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    def delete(self, request, application_id):
        
        try:
            application = ShiftApplication.objects.get(id=application_id)
        except ShiftApplication.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        application.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)

class EmployerView(APIView):
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

class ProfileView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                profile = Profile.objects.get(id=id)
            except Profile.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = profile_serializer.ProfileGetSerializer(profile, many=False)
        else:
            employers = Profile.objects.all().exclude(
                employer__isnull=True, employee__isnull=True
            )
            serializer = profile_serializer.ProfileGetSerializer(employers, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    # No POST request needed
    # as Profiles are created automatically along with User register

    def put(self, request, id):
        try:
            profile = Profile.objects.get(id=id)
        except Profile.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = profile_serializer.ProfileSerializer(profile, data=request.data, partial=True)
        userSerializer = user_serializer.UserUpdateSerializer(profile.user, data=request.data, partial=True)
        if serializer.is_valid() and userSerializer.is_valid():
            serializer.save()
            userSerializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProfileMeView(APIView):
    def get(self, request):
        if request.user.profile == None:
            raise PermissionDenied("You dont seem to have a profile")
            
        try:
            profile = Profile.objects.get(id=request.user.profile.id)
        except Profile.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = profile_serializer.ProfileGetSerializer(profile, many=False)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # No POST request needed
    # as Profiles are created automatically along with User register

    def put(self, request):
        if request.user.profile == None:
            raise PermissionDenied("You dont seem to have a profile")
            
        try:
            profile = Profile.objects.get(id=request.user.profile.id)
        except Profile.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        if "latitude" in request.data:
            request.data["latitude"] = round(request.data["latitude"], 6)
        if "longitude" in request.data:
            request.data["longitude"] = round(request.data["longitude"], 6) 
        
        serializer = profile_serializer.ProfileSerializer(profile, data=request.data, context={"request": request}, partial=True)
        userSerializer = user_serializer.UserUpdateSerializer(profile.user, data=request.data, partial=True)
        if serializer.is_valid() and userSerializer.is_valid():
            serializer.save()
            userSerializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProfileMeImageView(APIView):

    def put(self, request):
        if request.user.profile == None:
            raise PermissionDenied("You dont seem to have a profile")
            
        try:
            profile = Profile.objects.get(id=request.user.profile.id)
        except Profile.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)
        
        result = cloudinary.uploader.upload(
            request.FILES['image'],      
            public_id = 'profile'+str(request.user.profile.id), 
            crop = 'limit',
            width = 450,
            height = 450,
            eager = [
                { 
                    'width': 200, 'height': 200, 
                    'crop': 'thumb', 'gravity': 'face',
                    'radius': 100
                },
            ],                                     
            tags = ['profile_picture']
        )
        
        profile.picture = result['secure_url']
        profile.save()
        serializer = profile_serializer.ProfileSerializer(profile)

        return Response(serializer.data, status=status.HTTP_200_OK)

class EmployeeMeRatingsView(APIView):
    def get(self, request):
        if request.user.profile == None:
            raise PermissionDenied("You dont seem to have a profile")
            
        ratings = Rate.objects.filter(employee=request.user.profile.id)
        serializer = other_serializer.RateSerializer(ratings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class FavListView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                favList = FavoriteList.objects.get(id=id)
            except FavoriteList.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            if request.user.profile.employer.id != favList.employer.id:
                return Response("You are not allowed to access this information", status=status.HTTP_403_FORBIDDEN)
                
            serializer = favlist_serializer.FavoriteListGetSerializer(favList, many=False)
        else:
            
            is_employer = (request.user.profile.employer != None)
            if not is_employer:
                raise PermissionDenied("You are not allowed to access this information")
            else:
                favLists = FavoriteList.objects.all()
                favLists = favLists.filter(employer__id=request.user.profile.employer.id)
                serializer = favlist_serializer.FavoriteListGetSerializer(favLists, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = favlist_serializer.FavoriteListSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id):
        try:
            favList = FavoriteList.objects.get(id=id)
        except FavoriteList.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = favlist_serializer.FavoriteListSerializer(favList, data=request.data)
        if serializer.is_valid():
            serializer.save()
            
            serializedFavlist = favlist_serializer.FavoriteListGetSerializer(favList)
            return Response(serializedFavlist.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            favList = favlist_serializer.FavoriteList.objects.get(id=id)
        except FavoriteList.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        favList.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class FavListEmployeeView(APIView):
    def put(self, request, employee_id):
        
        if request.user.profile.employer == None:
            raise PermissionDenied("You are not allowed to have favorite lists")

        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = employee_serializer.EmployeeSerializer(employee, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class EmployeeMeShiftView(APIView, CustomPagination):
    def get(self, request):
        
        if (request.user.profile.employee == None):
            raise ValidationError("You don't seem to be an employee")
            
        shifts = Shift.objects.all().order_by('starting_at')
        
        qStatus = request.GET.get('status')
        if validators.in_choices(qStatus, SHIFT_STATUS_CHOICES):
            raise ValidationError('Invalid status')
        elif qStatus:
            shifts = shifts.filter(status__in = qStatus.split(","))
        
        qStatus = request.GET.get('not_status')
        if validators.in_choices(qStatus, SHIFT_STATUS_CHOICES):
            raise ValidationError('Invalid status')
        elif qStatus:
            shifts = shifts.filter(~Q(status = qStatus))
        
        qUpcoming = request.GET.get('upcoming')
        if qUpcoming == 'true':
            shifts = shifts.filter(starting_at__gte=TODAY)
        
        qFailed = request.GET.get('failed')
        if qFailed == 'true':
            shifts = shifts.filter(shiftemployee__success=False)
            
        shifts = shifts.filter(employees__in = (request.user.profile.employee.id,))
        
        serializer = shift_serializer.ShiftSerializer(shifts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ShiftView(APIView, CustomPagination):
    def get(self, request, id=False):
        if (id):
            try:
                shift = Shift.objects.get(id=id)
            except Shift.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = shift_serializer.ShiftGetSerializer(shift, many=False)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            shifts = Shift.objects.all().order_by('starting_at')
            
            qStatus = request.GET.get('status')
            if validators.in_choices(qStatus, SHIFT_STATUS_CHOICES):
                raise ValidationError('Invalid status')
            elif qStatus:
                shifts = shifts.filter(status__in = qStatus.split(","))
            
            qStatus = request.GET.get('not_status')
            if validators.in_choices(qStatus, SHIFT_STATUS_CHOICES):
                raise ValidationError('Invalid status')
            elif qStatus:
                shifts = shifts.filter(~Q(status = qStatus))
            
            qUpcoming = request.GET.get('upcoming')
            if qUpcoming == 'true':
                shifts = shifts.filter(starting_at__gte=TODAY)
            
            qUnrated = request.GET.get('unrated')
            if qUnrated == 'true':
                shifts = shifts.filter(rate_set=None)
                
            if request.user.profile.employer is None:
                shifts = shifts.filter(employees__in = (request.user.profile.id,))
            else:
                shifts = shifts.filter(employer = request.user.profile.employer.id)
            
            serializer = shift_serializer.ShiftSerializer(shifts, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):

        if(request.user.profile.employer == None):
            raise ValidationError('This user doesn\'t seem to be an employer, only employers can create shifts.')
        
        request.data["employer"] = request.user.profile.employer.id
        serializer = shift_serializer.ShiftPostSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id):
        try:
            shift = Shift.objects.get(id=id)
        except Shift.DoesNotExist:
            return Response({ "detail": "This shift was not found, talk to the employer for any more details about what happened."},status=status.HTTP_404_NOT_FOUND)
        serializer = shift_serializer.ShiftSerializer(shift, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            shift = Shift.objects.get(id=id)
        except Shift.DoesNotExist:
            return Response({ "detail": "This shift was not found, talk to the employer for any more details about what happened."}, status=status.HTTP_404_NOT_FOUND)

        shift.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ShiftCandidatesView(APIView, CustomPagination):
    def put(self, request, id):
        try:
            shift = Shift.objects.get(id=id)
        except Shift.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)
            
        serializer = shift_serializer.ShiftCandidatesSerializer(shift, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VenueView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                venue = Venue.objects.get(id=id)
            except Venue.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = venue_serializer.VenueSerializer(venue, many=False)
        else:
            venues = Venue.objects.all()
            serializer = venue_serializer.VenueSerializer(venues, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = venue_serializer.VenueSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id):
        try:
            venue = Venue.objects.get(id=id)
        except Venue.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = venue_serializer.VenueSerializer(venue, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            venue = Venue.objects.get(id=id)
        except Venue.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        venue.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class PositionView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                position = Position.objects.get(id=id)
            except Position.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = other_serializer.PositionSerializer(position, many=False)
        else:
            positions = Position.objects.all()
            serializer = other_serializer.PositionSerializer(positions, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = other_serializer.PositionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id):
        try:
            position = Position.objects.get(id=id)
        except Position.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = other_serializer.PositionSerializer(position, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            position = Position.objects.get(id=id)
        except Position.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        position.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class BadgeView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                badge = Badge.objects.get(id=id)
            except Badge.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = other_serializer.BadgeSerializer(badge, many=False)
        else:
            badges = Badge.objects.all()
            serializer = other_serializer.BadgeSerializer(badges, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = other_serializer.BadgeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id):
        try:
            badge = Badge.objects.get(id=id)
        except Badge.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = other_serializer.BadgeSerializer(badge, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            badge = Badge.objects.get(id=id)
        except Badge.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        badge.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class JobCoreInviteView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                invite = JobCoreInvite.objects.get(id=id)
            except JobCoreInvite.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = other_serializer.JobCoreInviteGetSerializer(invite, many=False)
        else:
            invites = JobCoreInvite.objects.all()
            serializer = other_serializer.JobCoreInviteGetSerializer(invites, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = other_serializer.JobCoreInvitePostSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id):
        try:
            invite = JobCoreInvite.objects.get(id=id)
        except JobCoreInvite.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        serializer = other_serializer.BadgeSerializer(invite, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        try:
            invite = JobCoreInvite.objects.get(id=id)
        except JobCoreInvite.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ShiftInviteView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                invite = ShiftInvite.objects.get(id=id)
            except ShiftInvite.DoesNotExist:
                return Response(validators.error_object('The invite was not found, maybe the shift does not exist anymore. Talk to the employer for any more details about this error.'), status=status.HTTP_404_NOT_FOUND)

            serializer = shift_serializer.ShiftInviteGetSerializer(invite, many=False)
        else:
            invites = ShiftInvite.objects.all()
            
            is_employer = (request.user.profile.employer != None)
            if is_employer:
                invites = invites.filter(sender__employer__id=request.user.profile.employer.id)
                qEmployee_id = request.GET.get('employee')
                if qEmployee_id:
                    invites = invites.filter(employer__id=qEmployee_id)
            elif (request.user.profile.employee == None):
                raise ValidationError('This user doesn\'t seem to be an employee or employer')
            else:
                invites = invites.filter(employee__id=request.user.profile.employee.id)
            
            qStatus = request.GET.get('status')
            if qStatus:
                invites = invites.filter(status=qStatus)
                
            serializer = shift_serializer.ShiftInviteGetSerializer(invites, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id, action):
        
        try:
            invite = ShiftInvite.objects.get(id=id)
        except ShiftInvite.DoesNotExist:
            return Response(validators.error_object('The invite was not found, maybe the shift does not exist anymore. Talk to the employer for any more details about this error.'), status=status.HTTP_404_NOT_FOUND)
        
        if action == 'apply':
            data={ "status": 'APPLIED' } 
        elif action == 'reject':
            data={ "status": 'REJECTED' } 
        else:
            raise ValidationError("You can either apply or reject an invite")

        shiftSerializer = shift_serializer.ShiftInviteSerializer(invite, data=data, many=False)
        appSerializer = shift_serializer.ShiftApplicationSerializer(data={
            "shift": invite.shift.id,
            "invite": invite.id,
            "employee": invite.employee.id
        }, many=False)
        if shiftSerializer.is_valid():
            if appSerializer.is_valid():
                shiftSerializer.save()
                appSerializer.save()
                
                return Response(appSerializer.data, status=status.HTTP_200_OK)
            else:
                return Response(appSerializer.errors, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(shiftSerializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def post(self, request):
        invites = []
        if request.user.profile.employer == None:
            raise PermissionDenied("You are not allowed to invite talents to shifts")
        # masive creation of shift invites
        if isinstance(request.data['shifts'],list):
            for s in request.data['shifts']:
                serializer = shift_serializer.ShiftInviteSerializer(data={
                    "employee": request.data['employee'],
                    "sender": request.user.profile.id,
                    "shift": s
                })
                if serializer.is_valid():
                    serializer.save()
                    invites.append(serializer.data)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        else:
            # add new invite to the shift
            serializer = shift_serializer.ShiftInviteSerializer(data={
                    "employee": request.data['employee'],
                    "sender": request.user.profile.id,
                    "shift": request.data['shifts']
                })
            if serializer.is_valid():
                serializer.save()
                invites.append(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(invites, status=status.HTTP_201_CREATED)
        
    def delete(self, request, id):
        try:
            invite = ShiftInvite.objects.get(id=id)
        except ShiftInvite.DoesNotExist:
            return Response(validators.error_object('The invite was not found, maybe the shift does not exist anymore. Talk to the employer for any more details about this error.'), status=status.HTTP_404_NOT_FOUND)

        invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ShiftMeInviteView(APIView):
    def get(self, request, id=False):
        
        if (request.user.profile.employee == None):
            raise ValidationError('You are not an employee or talent')
        
        invites = ShiftInvite.objects.filter(employee__id=request.user.profile.employee.id)
        
        qStatus = request.GET.get('status')
        if qStatus:
            invites = invites.filter(status=qStatus)
            
        serializer = shift_serializer.ShiftInviteGetSerializer(invites, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

class RateView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                rate = Rate.objects.get(id=id)
            except Rate.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = other_serializer.RateSerializer(rate, many=False)
        else:
            rates = Rate.objects.all()
            
            qEmployer = request.GET.get('employer')
            qEmployee = request.GET.get('employee')
            if qEmployee:
                rates = rates.filter(employee__id=qEmployee)
            elif qEmployer:
                rates = rates.filter(employee__id=qEmployer)
            
            qShift = request.GET.get('shift')
            if qShift:
                rates = rates.filter(shift__id=qShift)
                
            serializer = other_serializer.RateSerializer(rates, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):

        serializer = other_serializer.RateSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request, id):
        try:
            rate = Rate.objects.get(id=id)
        except Rate.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        rate.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class CatalogView(APIView):
    def get(self, request, catalog_type):
        
        if catalog_type == 'employees':
            employees = User.objects.exclude(employee__isnull=True)
            
            qName = request.GET.get('full_name')
            if qName:
                search_args = []
                for term in qName.split():
                    for query in ('profile__user__first_name__istartswith', 'profile__user__last_name__istartswith'):
                        search_args.append(Q(**{query: term}))
                
                employees = employees.filter(functools.reduce(operator.or_, search_args))

            qPositions = request.GET.getlist('positions')
            if qPositions:
                employees = employees.filter(positions__id__in=qPositions)

            qBadges = request.GET.getlist('badges')
            if qBadges:
                employees = employees.filter(badges__id__in=qBadges)
            
            employees = map(lambda emp: { "label": emp["first_name"] + ' ' + emp["last_name"], "value": emp["profile__employee__id"] }, employees.values('first_name', 'last_name', 'profile__employee__id'))
            return Response(employees, status=status.HTTP_200_OK)
        
        elif catalog_type == 'positions':
            positions = Position.objects.exclude()
            positions = map(lambda emp: { "label": emp["title"], "value": emp["id"] }, positions.values('title', 'id'))
            return Response(positions, status=status.HTTP_200_OK)
        
        elif catalog_type == 'badges':
            badges = Badge.objects.exclude()
            badges = map(lambda emp: { "label": emp["title"], "value": emp["id"] }, badges.values('title', 'id'))
            return Response(badges, status=status.HTTP_200_OK)
            
        return Response("no catalog", status=status.HTTP_200_OK)

class DeviceMeView(APIView):
    def get(self, request, device_id=None):
        
        if request.user is None:
            return Response(validators.error_object('You have to be loged in'), status=status.HTTP_400_BAD_REQUEST)
        
        if device_id is not None:
            try:
                device = FCMDevice.objects.get(registration_id=device_id, user=request.user.id)
                serializer = notification_serializer.FCMDeviceSerializer(device, many=False)
                return Response(serializer.data, status=status.HTTP_200_OK)
            except FCMDevice.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)
        else:
            devices = FCMDevice.objects.filter(user=request.user.id)
            serializer = notification_serializer.FCMDeviceSerializer(devices, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
    def put(self, request, device_id):
        
        if request.user is None:
            return Response(validators.error_object('No user was identified'), status=status.HTTP_400_BAD_REQUEST)
        
        try:
            device = FCMDevice.objects.get(registration_id=device_id, user=request.user.id)
            serializer = notification_serializer.FCMDeviceSerializer(device, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data,status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except FCMDevice.DoesNotExist:
            return Response(validators.error_object('Device not found'), status=status.HTTP_404_NOT_FOUND)
            
    def delete(self, request, device_id=None):
        
        if request.user is None:
            return Response(validators.error_object('No user was identified'), status=status.HTTP_400_BAD_REQUEST)
        
        try:
            if device_id is None:
                devices = FCMDevice.objects.filter(user=request.user.id)
                devices.delete()
            else:
                device = FCMDevice.objects.get(registration_id=device_id, user=request.user.id)
                device.delete()
                
            return Response(status=status.HTTP_204_NO_CONTENT)
        except FCMDevice.DoesNotExist:
            return Response(validators.error_object('Device not found'), status=status.HTTP_404_NOT_FOUND)
            
class ClockinsView(APIView):
    def get(self, request, id=False):
        if (id):
            try:
                rate = Clockin.objects.get(id=user_id)
            except Clockin.DoesNotExist:
                return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

            serializer = clockin_serializer.ClockinSerializer(rate, many=False)
        else:
            clockins = Clockin.objects.all()
            
            qEmployee = request.GET.get('employee')
            qShift = request.GET.get('shift')
            if qEmployee:
                clockins = clockins.filter(employee__id=qEmployee)
            elif qShift:
                clockins = clockins.filter(shift__id=qShift)
                
            serializer = clockin_serializer.ClockinSerializer(clockins, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = clockins_serializer.ClockinSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request, clockin_id):
        try:
            clockin = Clockin.objects.get(id=clockin_id)
        except Clockin.DoesNotExist:
            return Response(validators.error_object('Not found.'), status=status.HTTP_404_NOT_FOUND)

        clockin.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ClockinsMeView(APIView):
    def get(self, request, id=False):
        
        if request.user.profile.employee == None:
            raise ValidationError('You are not an employee')
            
        clockins = Clockin.objects.filter(employee_id=request.user.profile.employee.id)
        
        qShift = request.GET.get('shift')
        if qShift:
            clockins = clockins.filter(shift__id=qShift)
            
        serializer = clockin_serializer.ClockinGetSerializer(clockins, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        
        if request.user.profile.employee == None:
            raise PermissionDenied("You are not allowed to check in or out yourself")
            
        request.data['employee'] = request.user.profile.employee.id
        try:
            clockin = Clockin.objects.get(shift=request.data["shift"], employee=request.data["employee"])
            serializer = clockin_serializer.ClockinSerializer(clockin, data=request.data, context={"request": request})
        except Clockin.DoesNotExist:
            serializer = clockin_serializer.ClockinSerializer(data=request.data, context={"request": request})
            pass
        
        if serializer.is_valid():
            serializer.save()
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
class PayrollView(APIView, CustomPagination):
    def get(self, request):

        clockins = Clockin.objects.all()

        qStatus = request.GET.get('status')
        if qStatus is not None:
            clockins = Clockin.objects.filter(status = qStatus)
        
        qShift = request.GET.get('shift')
        if qShift is not None and qShift is not '':
            clockins = clockins.filter(shift=qShift)
        else:    
            qEnded_at = request.GET.get('ending_at')
            if qEnded_at is not None and qEnded_at is not '':
                clockins = clockins.filter(ended_at__lte=qEnded_at)
    
            qStarted_at = request.GET.get('starting_at')
            if qStarted_at is not None and qStarted_at is not '':
                clockins = clockins.filter(started_at__gte=qStarted_at)
            
        payrolDic = {}
        for clockin in clockins:
            clockinSerialized = clockin_serializer.ClockinGetSerializer(clockin)
            if str(clockin.employee.id) in payrolDic:
                payrolDic[str(clockin.employee.id)]["clockins"].append(clockinSerialized.data)
            else:
                employeeSerialized = employee_serializer.EmployeeGetSmallSerializer(clockin.employee)
                payrolDic[str(clockin.employee.id)] = {
                    "clockins": [clockinSerialized.data],
                    "talent": employeeSerialized.data
                }
        
        payrol = []
        for key, value in payrolDic.items():
            payrol.append(value)
            
        return Response(payrol, status=status.HTTP_200_OK)
    
    def put(self, request, id):
        
        if (request.user.profile.employer == None):
            raise ValidationError("You don't seem to be an employer")
        
        try:
            emp = Employee.objects.get(id=id)
        except Employee.DoesNotExist:
            return Response({ "detail": "The employee was not found"},status=status.HTTP_404_NOT_FOUND)
        
        _serializers = []
        for clockin in request.data:
            try:
                old_clockin = Clockin.objects.get(id=clockin["id"])
                serializer = clockin_serializer.ClockinPayrollSerializer(old_clockin, data=clockin)
            except Clockin.DoesNotExist:
                serializer = clockin_serializer.ClockinPayrollSerializer(data=clockin)
                
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            _serializers.append(serializer)
        
        for serializer in _serializers:   
            serializer.save()
        
        return Response(serializer.data, status=status.HTTP_200_OK)