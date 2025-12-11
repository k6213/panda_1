from rest_framework import serializers
from .models import Customer, ConsultationLog

# 1. 상담 로그용 시리얼라이저
class LogSerializer(serializers.ModelSerializer):
    writer_name = serializers.ReadOnlyField(source='writer.username') # 작성자 이름 표시
    created_at_fmt = serializers.DateTimeField(format="%Y-%m-%d %H:%M", read_only=True) # 날짜 예쁘게

    class Meta:
        model = ConsultationLog
        fields = ['id', 'writer_name', 'content', 'created_at_fmt']

# 2. 고객용 시리얼라이저 (로그 포함)
class CustomerSerializer(serializers.ModelSerializer):
    logs = LogSerializer(many=True, read_only=True) # 고객 정보에 상담 로그 리스트 포함!
    net_profit = serializers.ReadOnlyField() # 순수익 자동계산 필드 포함

    class Meta:
        model = Customer
        fields = '__all__'