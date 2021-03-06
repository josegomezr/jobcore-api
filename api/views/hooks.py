from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly

from api.models import Employee, Shift, ShiftInvite, ShiftApplication
from api.actions import employee_actions

class DefaultAvailabilityHook(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        employees = Employee.objects.all()
        for emp in employees:
            employee_actions.create_default_availablity(emp)
            
        return Response({"status":"ok"}, status=status.HTTP_200_OK)

class DeleteAllShifts(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        
        ShiftInvite.objects.all().delete()
        ShiftApplication.objects.all().delete()
        Shift.objects.all().delete()
            
        return Response({"status":"ok"}, status=status.HTTP_200_OK)
