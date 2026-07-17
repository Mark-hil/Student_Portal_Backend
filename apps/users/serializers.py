"""User serializers — registration, profile, password change."""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import UserProfile

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UserProfile
        fields = ["enrollment_year", "graduation_year", "major", "gpa", "total_credits", "preferences"]


class UserSerializer(serializers.ModelSerializer):
    profile   = UserProfileSerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model  = User
        fields = [
            "id", "email", "student_id", "first_name", "last_name", "full_name",
            "role", "avatar", "phone", "department", "bio",
            "email_verified", "created_at", "profile",
        ]
        read_only_fields = ["id", "email", "role", "email_verified", "created_at", "student_id"]


class RegisterSerializer(serializers.Serializer):
    email      = serializers.EmailField()
    password   = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150)
    last_name  = serializers.CharField(max_length=150)
    role       = serializers.ChoiceField(choices=["student", "instructor"], default="student")

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password     = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, data):
        user = self.context["request"].user
        if not user.check_password(data["current_password"]):
            raise serializers.ValidationError({"current_password": "Incorrect current password."})
        return data


class AdminCreateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "id", "email", "password", "first_name", "last_name", "role", 
            "department", "phone"
        ]

    def validate_password(self, value):
        if value:
            validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        UserProfile.objects.get_or_create(user=user)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
