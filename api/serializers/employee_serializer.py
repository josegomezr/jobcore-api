from api.serializers import other_serializer, favlist_serializer
from rest_framework import serializers
from api.models import Employee, Profile, User, FavoriteList

#
# NESTED
#

class ProfileGetSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('picture', 'bio')

class UserGetSmallSerializer(serializers.ModelSerializer):
    profile = ProfileGetSmallSerializer(many=False)
    
    class Meta:
        model = User
        fields = ('first_name','last_name', 'email', 'profile')

#
# MAIN
#
class EmployeeGetTinySerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        exclude = ()
        
class EmployeeGetSmallSerializer(serializers.ModelSerializer):
    user = UserGetSmallSerializer(many=False)
    favoritelist_set = favlist_serializer.FavoriteListSerializer(many=True)
    class Meta:
        model = Employee
        exclude = ()

class EmployeeGetSerializer(serializers.ModelSerializer):
    positions = other_serializer.PositionSerializer(many=True)
    favoritelist_set = favlist_serializer.FavoriteListSerializer(many=True)
    user = UserGetSmallSerializer(many=False)

    class Meta:
        model = Employee
        exclude = ()

class EmployeeSerializer(serializers.ModelSerializer):
    #favoritelist_set = serializers.PrimaryKeyRelatedField(many=True, queryset=FavoriteList.objects.all())
    
    class Meta:
        model = Employee
        exclude = ()
        extra_kwargs = {
            'id': {'read_only': True},
            'user': {'read_only': True},
            'rating': {'read_only': True},
            'job_count': {'read_only': True},
            'badges': {'read_only': True}
        }
        
    def validate(self, data):
        employee = self.instance
        if employee.minimum_hourly_rate < 8:
            raise serializers.ValidationError('The minimum hourly rate allowed is 8 dollars')
        if employee.maximum_job_distance_miles < 10:
            raise serializers.ValidationError('The minimum distance allowed is 10 miles')
        elif employee.maximum_job_distance_miles > 100:
            raise serializers.ValidationError('The maximum distance allowed is 100 miles')
            
        return data

#to update the employee favorite lists
class EmployeeFavlistSerializer(serializers.ModelSerializer):
    favoritelist_set = serializers.PrimaryKeyRelatedField(many=True, queryset=FavoriteList.objects.all())
    
    class Meta:
        model = Employee
        exclude = ()

class EmployeeSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        exclude = ()
        extra_kwargs = {
            'id': {'read_only': True},
            'user': {'read_only': True},
            'rating': {'read_only': True},
            'job_count': {'read_only': True},
            'badges': {'read_only': True}
        }
        
    def validate(self, data):
        employee = self.instance
        if 'minimum_hourly_rate' in data and data['minimum_hourly_rate'] < 8:
            raise serializers.ValidationError('The minimum hourly rate allowed is 8 dollars')
            
        if 'maximum_job_distance_miles' in data:
            if data['maximum_job_distance_miles'] < 10:
                raise serializers.ValidationError('The minimum distance allowed is 10 miles')
            elif data['maximum_job_distance_miles'] > 100:
                raise serializers.ValidationError('The maximum distance allowed is 100 miles')
            
        return data
        
    