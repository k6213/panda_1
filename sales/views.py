import os
import json
import datetime
import re
import requests
from django.utils import timezone
from django.contrib.auth import authenticate
from django.db.models import Sum, Count, Q, F, Case, When, IntegerField, Value, FloatField
from django.db.models.functions import Coalesce, Cast
from django.shortcuts import get_object_or_404
from django.http import HttpResponse

# DRF 관련 임포트
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from rest_framework.parsers import MultiPartParser, FormParser
from requests.auth import HTTPBasicAuth

# 모델 및 시리얼라이저
from .models import (
    Customer, User, ConsultationLog, Platform, 
    FailureReason, CustomStatus, SettlementStatus, SalesProduct, SMSLog,
    AdChannel, Bank, Notice, PolicyImage, TodoTask, CancelReason, Client
)
from .serializers import (
    CustomerSerializer, UserSerializer, PlatformSerializer, 
    ReasonSerializer, StatusSerializer, SettlementStatusSerializer, 
    SalesProductSerializer, LogSerializer,
    AdChannelSerializer, BankSerializer, NoticeSerializer, PolicyImageSerializer, TodoTaskSerializer, CancelReasonSerializer, ClientSerializer
)

from .system_config import CONFIG_DATA

# [유틸리티] 전화번호 정규화
def clean_phone(phone):
    if not phone: return ""
    cleaned = re.sub(r'[^0-9]', '', str(phone))
    if cleaned.startswith('82') and len(cleaned) > 10:
        cleaned = '0' + cleaned[2:]
    return cleaned

# ==============================================================================
# [핵심] 문자 발송 함수
# ==============================================================================
# views.py 수정
# views.py 수정
def send_traccar_cloud_sms(phone, sms_text, gateway_config):
    url = gateway_config.get('url')
    username = gateway_config.get('username')
    password = gateway_config.get('password')

    if not all([url, username, password]):
        return False

    # 📱 [중요] 전화번호를 +8210... 형식으로 변환
    # 모든 특수문자 제거
    raw_num = re.sub(r'[^0-9]', '', str(phone))
    if raw_num.startswith('0'):
        # 앞의 0을 제거하고 +82를 붙임 (01012345678 -> +821012345678)
        formatted_phone = '+82' + raw_num[1:]
    elif raw_num.startswith('82'):
        formatted_phone = '+' + raw_num
    else:
        formatted_phone = '+82' + raw_num

    payload = {
        "textMessage": {
            "text": sms_text
        },
        "phoneNumbers": [formatted_phone] # 👈 변환된 번호 사용
    }

    try:
        response = requests.post(
            url, 
            json=payload, 
            auth=HTTPBasicAuth(username, password), 
            timeout=5
        )
        
        if response.status_code in [200, 201, 202]:
            print(f"✅ 발송 성공: {formatted_phone}")
            return True
        else:
            # 400 에러 메시지를 로그에 더 자세히 출력
            print(f"❌ 발송 실패: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 연결 오류: {e}")
        return False

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_sms_connection(request):
    # 1. 리액트가 보낸 데이터(번호, 설정값)를 꺼냄
    phone = request.data.get('phone')
    gateway_config = request.data.get('gateway_config') # 리액트의 smsConfig 객체

    if not phone or not gateway_config:
        return Response({"message": "번호나 설정값이 없습니다."}, status=400)

    # 2. 위에서 만든 '엔진' 함수를 실행
    test_msg = "[연동테스트] 서버와 휴대폰이 연결되었습니다."
    success = send_traccar_cloud_sms(clean_phone(phone), test_msg, gateway_config)

    # 3. 결과에 따라 리액트에 응답을 보냄
    if success:
        return Response({"message": "테스트 문자 발송 성공!"})
    else:
        return Response({"message": "발송 실패! 설정값을 확인하세요."}, status=500)
# ==============================================================================
# 1. 인증 및 기기 연결
# ==============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def login_api(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(username=username, password=password)
    
    if user is not None:
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'message': '로그인 성공!', 
            'token': token.key,
            'user_id': user.id, 
            'username': user.username, 
            'role': user.role,
            'fcm_token': user.fcm_token
        })
    return Response({'message': 'ID 또는 비밀번호가 틀립니다.'}, status=400)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_fcm_token_view(request):
    fcm_token = request.data.get('fcm_token')
    if not fcm_token:
        return Response({'message': '토큰값이 없습니다.'}, status=400)
    user = request.user
    user.fcm_token = fcm_token
    user.save()
    return Response({'status': 'success', 'message': '📱 기기 연동 완료!', 'agent': user.username})

# ==============================================================================
# 2. SMS 및 고객 유입
# ==============================================================================

# sales/views.py 내의 SMSReceiveView 클래스 수정

class SMSReceiveView(APIView):
    permission_classes = [AllowAny] 

    def post(self, request):
        data = request.data
        print(f"📥 웹훅 수신 데이터: {data}") # 디버깅용 로그

        # 🟢 공식 문서 규격에 맞게 데이터 추출
        if 'payload' in data:
            # 웹훅 등록 방식으로 올 경우
            payload = data.get('payload', {})
            from_num = payload.get('phoneNumber')
            msg_content = payload.get('message')
        else:
            # 그 외 일반적인 전송 방식일 경우 (예비용)
            from_num = data.get('from') or data.get('sender')
            msg_content = data.get('message') or data.get('text')

        if not from_num or not msg_content:
            return Response({"message": "데이터가 부족합니다."}, status=400)

        # 전화번호 정규화 (+8210... -> 010...)
        clean_num = clean_phone(from_num)
        
        # 번호 뒷 8자리가 일치하는 고객 찾기
        customer = Customer.objects.filter(phone__contains=clean_num[-8:]).first()
        
        if customer:
            # 🟢 수신된 메시지를 DB에 저장 (IN 방향)
            SMSLog.objects.create(
                customer=customer, 
                agent=customer.owner, 
                content=msg_content, 
                direction='IN', 
                status='RECEIVED'
            )
            # 고객 상태가 '부재'였다면 '재통'으로 자동 변경 (선택사항)
            if customer.status == '부재':
                customer.status = '재통'
                customer.save()
            
            print(f"✅ {customer.name}님의 답장 저장 완료!")
            return Response({"status": "success"}, status=200)
        else:
            print(f"❓ 등록되지 않은 번호의 문자: {clean_num}")
            return Response({"status": "ignored", "message": "등록되지 않은 고객입니다."}, status=200)

class LeadCaptureView(APIView):
    permission_classes = [AllowAny] 
    def post(self, request):
        phone = clean_phone(request.data.get('phone', ''))
        agent_id = request.data.get('agent_id')
        name = request.data.get('name', '신규문의')
        custom_message = request.data.get('message') 
        platform = request.data.get('platform', '기타')

        if not phone: return Response({"message": "연락처 필수"}, status=400)
        
        agent = None
        if agent_id: 
            agent = User.objects.filter(id=agent_id).first()
        
        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={'name': name, 'owner': agent, 'status': '미통건', 'platform': platform}
        )

        if custom_message:
            log = SMSLog.objects.create(customer=customer, agent=agent, content=custom_message, direction='OUT', status='PENDING')
            if send_traccar_cloud_sms(phone, custom_message):
                log.status = 'SUCCESS'; log.save()
            else:
                log.status = 'FAIL'; log.save()
        
        return Response({"message": "고객 등록 완료", "customer_id": customer.id}, status=201)

# views.py 내의 send_manual_sms 함수 수정
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_manual_sms(request):
    customer_id = request.data.get('customer_id')
    sms_text = request.data.get('message', '').strip()
    image_file = request.FILES.get('image')
    
    # 🟢 [추가] 프론트엔드에서 보낸 기기 설정값 받기
    # FormData(MultiPart)로 데이터가 오므로 문자열 형태를 JSON으로 파싱해야 합니다.
    gateway_config_raw = request.data.get('gateway_config')
    try:
        gateway_config = json.loads(gateway_config_raw) if gateway_config_raw else None
    except:
        gateway_config = gateway_config_raw # 이미 객체인 경우

    agent = request.user
    customer = get_object_or_404(Customer, id=customer_id)

    if not sms_text and not image_file:
        return Response({"message": "내용 또는 이미지가 필요합니다."}, status=400)

    if not gateway_config:
        return Response({"message": "문자 발송 기기 설정 정보가 없습니다."}, status=400)

    if not sms_text and image_file:
        sms_text = "(사진 첨부)"

    log = SMSLog.objects.create(
        customer=customer, 
        agent=agent, 
        content=sms_text, 
        image=image_file,
        direction='OUT', 
        status='PENDING'
    )

    # 🔴 [수정] 3번째 인자로 gateway_config를 전달합니다.
    if send_traccar_cloud_sms(customer.phone, sms_text, gateway_config):
        log.status = 'SUCCESS'; log.save()
        return Response({"message": "전송 성공", "log_id": log.id}, status=200)
    else:
        log.status = 'FAIL'; log.save()
        return Response({"message": "발송 실패 (기기 연결 확인)", "log_id": log.id}, status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_sms_history(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    logs = SMSLog.objects.filter(customer=customer).order_by('created_at')
    
    data = []
    for l in logs:
        # 🟢 [추가] 이미지가 있으면 URL 생성, 없으면 None
        image_url = None
        if l.image:
            image_url = request.build_absolute_uri(l.image.url)

        data.append({
            'id': l.id,
            'sender': 'me' if l.direction == 'OUT' else 'other',
            'text': l.content,
            'image': image_url, # 🟢 [추가] 프론트엔드로 이미지 주소 전달
            'created_at': l.created_at.strftime("%Y-%m-%d %H:%M"),
            'status': l.status
        })
        
    return Response(data)

# ==============================================================================
# 3. ⭐️ [업그레이드] 통계 및 데이터 분석 API (StatisticsView)
# ==============================================================================

class StatisticsView(APIView):
    """
    📊 통합 통계 API (플랫폼별 광고비 단가 적용)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        platform_filter = request.query_params.get('platform', 'ALL')
        
        queryset = Customer.objects.all()
        
        # 1. 기간 필터
        if start_date:
            if len(start_date) == 10:  # 일별
                if not end_date: end_date = start_date 
                queryset = queryset.filter(upload_date__range=[start_date, end_date])
            elif len(start_date) == 7: # 월별
                queryset = queryset.filter(upload_date__startswith=start_date)

        # 2. 플랫폼 필터
        if platform_filter != 'ALL':
            queryset = queryset.filter(platform=platform_filter)

        # 정책금 단위 보정
        agent_policy_val = Cast(Coalesce(F('agent_policy'), Value(0)), IntegerField())
        support_amt_val = Cast(Coalesce(F('support_amt'), Value(0)), IntegerField())
        revenue_expression = (agent_policy_val - support_amt_val) * 10000

        # 3. 데이터 집계
        raw_stats = queryset.values('owner', 'owner__username', 'platform').annotate(
            total_db=Count('id'),
            ad_target_count=Count('id', filter=~Q(status__in=['AS요청', '실패', '중복', '실패이관'])),
            accepted_count=Count('id', filter=Q(status__in=['접수완료', '설치완료', '해지진행'])),
            installed_count=Count('id', filter=Q(status='설치완료')),
            canceled_count=Count('id', filter=Q(status='접수취소')),
            accepted_revenue=Sum(Case(When(status__in=['접수완료', '설치완료', '해지진행'], then=revenue_expression), default=0, output_field=IntegerField())),
            installed_revenue=Sum(Case(When(status='설치완료', then=revenue_expression), default=0, output_field=IntegerField()))
        ).order_by('owner')

        # ⭐️ [핵심 수정] 광고 채널 단가 로드
        # 예: {'당근': 10000, '토스': 15000, ...}
        ad_costs = { ac.name: ac.cost for ac in AdChannel.objects.all() }

        # 모든 유저 기본값 세팅
        all_users = User.objects.all()
        agent_map = {
            str(u.id): {
                "id": str(u.id), "name": u.username, 
                "db": 0, "adTargetDb": 0, "accepted": 0, "installed": 0, "canceled": 0,
                "acceptedRevenue": 0, "installedRevenue": 0, 
                "adSpend": 0, # 🟢 서버에서 계산된 총 광고비
                "platformDetails": []
            } for u in all_users
        }
        agent_map['unknown'] = {
            "id": "unknown", "name": "미배정", 
            "db": 0, "adTargetDb": 0, "accepted": 0, "installed": 0, "canceled": 0,
            "acceptedRevenue": 0, "installedRevenue": 0, "adSpend": 0,
            "platformDetails": []
        }

        # 4. 집계 및 광고비 계산
        for row in raw_stats:
            owner_id = str(row['owner']) if row['owner'] else 'unknown'
            if owner_id not in agent_map: continue 

            agent = agent_map[owner_id]
            platform_name = row['platform'] or '기타'
            
            # 수치 합산
            db_count = (row['total_db'] or 0)
            ad_target_db = (row['ad_target_count'] or 0)

            agent['db'] += db_count
            agent['adTargetDb'] += ad_target_db
            agent['accepted'] += (row['accepted_count'] or 0)
            agent['installed'] += (row['installed_count'] or 0)
            agent['canceled'] += (row['canceled_count'] or 0)
            agent['acceptedRevenue'] += (row['accepted_revenue'] or 0)
            agent['installedRevenue'] += (row['installed_revenue'] or 0)

            # 🟢 [핵심] 플랫폼별 광고비 계산 (단가 * 유효DB수)
            # 단가가 없으면 기본 0원 처리
            unit_cost = ad_costs.get(platform_name, 0)
            platform_ad_spend = ad_target_db * unit_cost
            
            agent['adSpend'] += platform_ad_spend # 총 광고비에 누적

            agent['platformDetails'].append({
                "name": platform_name,
                "db": db_count,
                "adTargetDb": ad_target_db,
                "accepted": (row['accepted_count'] or 0),
                "installed": (row['installed_count'] or 0),
                "canceled": (row['canceled_count'] or 0),
                "acceptedRevenue": (row['accepted_revenue'] or 0),
                "installedRevenue": (row['installed_revenue'] or 0),
                "adSpend": platform_ad_spend # 플랫폼별 광고비
            })

        final_results = []

        # 5. 최종 마진/수익율 계산
        for agent in agent_map.values():
            # 순수익 = 설치매출 - 광고비
            agent['netProfit'] = agent['installedRevenue'] - agent['adSpend']
            agent['avgMargin'] = round(agent['acceptedRevenue'] / agent['accepted']) if agent['accepted'] > 0 else 0
            agent['acceptRate'] = round((agent['accepted'] / agent['db'] * 100), 1) if agent['db'] > 0 else 0
            
            total_receipts = agent['accepted'] + agent['canceled']
            agent['cancelRate'] = round((agent['canceled'] / total_receipts * 100), 1) if total_receipts > 0 else 0
            agent['netInstallRate'] = round((agent['accepted'] / agent['db'] * 100), 1) if agent['db'] > 0 else 0

            # 플랫폼별 데이터도 동일 로직 적용
            for pf in agent['platformDetails']:
                pf['netProfit'] = pf['installedRevenue'] - pf['adSpend']
                pf['avgMargin'] = round(pf['acceptedRevenue'] / pf['accepted']) if pf['accepted'] > 0 else 0
                pf['acceptRate'] = round((pf['accepted'] / pf['db'] * 100), 1) if pf['db'] > 0 else 0
                
                pf_total_receipts = pf['accepted'] + pf['canceled']
                pf['cancelRate'] = round((pf['canceled'] / pf_total_receipts * 100), 1) if pf_total_receipts > 0 else 0
                pf['netInstallRate'] = round((pf['accepted'] / pf['db'] * 100), 1) if pf['db'] > 0 else 0
                
                # 순이익율
                p_revenue = pf['acceptedRevenue'] + pf['installedRevenue']
                pf['netProfitMargin'] = round((pf['netProfit'] / p_revenue * 100), 1) if p_revenue > 0 else 0

            # DB수 많은 순으로 플랫폼 정렬
            agent['platformDetails'].sort(key=lambda x: x['db'], reverse=True)
            
            # 전체 순이익율
            t_revenue = agent['acceptedRevenue'] + agent['installedRevenue']
            agent['netProfitMargin'] = round((agent['netProfit'] / t_revenue * 100), 1) if t_revenue > 0 else 0

            final_results.append(agent)

        # 설치 매출 순으로 상담사 정렬
        final_results.sort(key=lambda x: x['installedRevenue'], reverse=True)

        return Response(final_results)

# ... (나머지 ViewSet들은 기존과 동일하므로 생략 가능, 위 StatisticsView가 핵심) ...
class SystemConfigView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        response = Response(CONFIG_DATA)
        response['Cache-Control'] = 'public, max-age=86400' 
        return response

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    def create(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        if User.objects.filter(username=username).exists(): return Response({'message': '중복된 아이디'}, status=400)
        User.objects.create_user(username=username, password=password, role='AGENT')
        return Response({'message': '등록 완료'}, status=201)

class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN': return Customer.objects.all().order_by('-upload_date', '-created_at')
        return Customer.objects.filter(Q(owner=user) | Q(owner__isnull=True)).order_by('-upload_date', '-created_at')
    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    @action(detail=True, methods=['post'])
    def add_log(self, request, pk=None):
        customer = self.get_object()
        ConsultationLog.objects.create(customer=customer, writer=request.user, content=request.data.get('content'))
        return Response({'status': 'success'})
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        customer = self.get_object()
        target_user_id = request.data.get('user_id')
        if target_user_id: customer.owner = get_object_or_404(User, id=target_user_id)
        else: customer.owner = request.user
        customer.status = '재통'
        customer.save()
        return Response({'message': '배정 완료'})
    @action(detail=False, methods=['post'])
    def allocate(self, request):
        ids = request.data.get('customer_ids', [])
        agent_id = request.data.get('agent_id')
        if agent_id: agent = get_object_or_404(User, id=agent_id); Customer.objects.filter(id__in=ids).update(owner=agent, status='재통')
        else: Customer.objects.filter(id__in=ids).update(owner=request.user, status='재통')
        return Response({'message': '일괄 배정 완료'})

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        data = request.data.get('customers', [])
        cnt = 0
        
        for item in data:
            if not item.get('phone'): continue
            
            # 🟢 [수정됨] 프론트엔드에서 보낸 담당자(owner_id)와 상태(status) 받기
            owner_id = item.get('owner_id')
            status_val = item.get('status', '미통건') # 값이 없으면 '미통건' 기본값
            last_memo = item.get('last_memo')         # 엑셀의 상담 내용

            # 담당자 객체 찾기 (ID가 있을 경우)
            owner_obj = None
            if owner_id:
                try:
                    owner_obj = User.objects.get(id=owner_id)
                except User.DoesNotExist:
                    owner_obj = None

            # 🟢 [수정됨] DB 생성 시 담당자와 상태값 적용
            customer = Customer.objects.create(
                phone=clean_phone(item['phone']), 
                name=item.get('name', '미상'), 
                upload_date=datetime.date.today(), 
                status=status_val,        # 👈 탭에 맞는 상태 (접수완료/장기가망 등)
                owner=owner_obj,          # 👈 탭에 맞는 담당자 (나)
                platform=item.get('platform', '기타')
            )

            # 🟢 [수정됨] 상담 메모가 있다면 로그와 함께 저장
            if last_memo:
                customer.last_memo = last_memo
                customer.save()
                ConsultationLog.objects.create(
                    customer=customer,
                    writer=owner_obj if owner_obj else request.user, # 담당자 혹은 업로더
                    content=f"[초기메모] {last_memo}"
                )

            cnt += 1
            
        return Response({'message': f'{cnt}건 등록 완료', 'count': cnt})

    @action(detail=False, methods=['post'])
    def referral(self, request):
        data = request.data
        user = request.user
        Customer.objects.create(name=data.get('name', '지인소개'), phone=clean_phone(data.get('phone')), platform=data.get('platform', '지인'), status='접수완료', owner=user, upload_date=datetime.date.today(), product_info=data.get('product_info', ''))
        return Response({'message': '지인 접수 등록 완료'}, status=201)
        
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        customer = self.get_object()
        
        # related_name='logs'로 설정되어 있다고 가정 (ConsultationLog 모델 등)
        # 만약 에러나면 customer.consultationlog_set.all() 로 변경 시도
        logs = customer.logs.all().order_by('-created_at') 
        
        from .serializers import LogSerializer
        serializer = LogSerializer(logs, many=True)
        
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def start_chat(self, request):
        """
        📱 번호를 입력받아 채팅방을 조회하거나 새로 생성함
        """
        raw_phone = request.data.get('phone')
        phone = clean_phone(raw_phone) # 하이픈 제거 및 정규화
        
        if not phone or len(phone) < 10:
            return Response({"message": "유효한 전화번호를 입력해주세요."}, status=400)

        # 1. 기존 고객이 있는지 확인 (전체 DB 기준)
        customer = Customer.objects.filter(phone=phone).first()

        if customer:
            # 2-1. 이미 있다면: 담당자 확인
            if not customer.owner:
                # 담당자가 없다면 나에게 배정
                customer.owner = request.user
                customer.save()
                message = "미배정 DB를 나에게 배정하고 채팅방을 열었습니다."
            elif customer.owner == request.user:
                message = "기존 상담중인 채팅방을 열었습니다."
            else:
                # 다른 사람의 담당인 경우 안내만 하고 정보 반환
                return Response({
                    "message": f"이미 {customer.owner.username}님이 상담 중인 번호입니다.",
                    "customer": CustomerSerializer(customer).data,
                    "is_other_owner": True
                }, status=200)
        else:
            # 2-2. 없다면: 새로 생성하고 나에게 배정
            customer = Customer.objects.create(
                phone=phone,
                name=request.data.get('name', f"신규_{phone[-4:]}"),
                owner=request.user,
                status='미통건',
                platform='기타',
                upload_date=datetime.date.today(),
                last_memo="채팅 검색을 통해 새 방이 생성되었습니다."
            )
            # 로그 생성
            ConsultationLog.objects.create(
                customer=customer,
                writer=request.user,
                content="[시스템] 신규 번호 입력을 통해 채팅방 개설"
            )
            message = "새로운 채팅방이 생성되었습니다."

        serializer = self.get_serializer(customer)
        return Response({
            "message": message,
            "customer": serializer.data
        }, status=200)
        

class NoticeViewSet(viewsets.ModelViewSet):
    queryset = Notice.objects.all().order_by('-is_important', '-created_at'); serializer_class = NoticeSerializer; permission_classes = [IsAuthenticated]
    def perform_create(self, serializer): serializer.save(writer=self.request.user)

class PolicyImageViewSet(viewsets.ModelViewSet):
    queryset = PolicyImage.objects.all()
    serializer_class = PolicyImageSerializer
    permission_classes = [IsAuthenticated] # 필요시 주석 해제

    # sales/views.py 파일의 해당 부분

    @action(detail=False, methods=['get'])
    def latest(self, request):
        data = {}
        platforms = PolicyImage.objects.values_list('platform', flat=True).distinct()
        
        for p in platforms:
            images = PolicyImage.objects.filter(platform=p).order_by('-updated_at')
            data[p] = [
                {
                    "id": img.id, 
                    "url": request.build_absolute_uri(img.image.url) if img.image else None
                } 
                for img in images if img.image
            ]
        return Response(data)

    # 📤 [업로드] 여러 장의 이미지를 한 번에 저장
    def create(self, request, *args, **kwargs):
        platform = request.data.get('platform')
        images = request.FILES.getlist('image')

        if not images:
            return Response({"message": "업로드할 이미지가 없습니다."}, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        for img in images:
            PolicyImage.objects.create(
                platform=platform,
                image=img
            )
            created_count += 1

        return Response({
            "message": f"{created_count}장의 이미지가 성공적으로 업로드되었습니다.",
            "status": "success"
        }, status=status.HTTP_201_CREATED)

class PlatformViewSet(viewsets.ModelViewSet): queryset = Platform.objects.all(); serializer_class = PlatformSerializer; permission_classes = [IsAuthenticated]
class FailureReasonViewSet(viewsets.ModelViewSet): queryset = FailureReason.objects.all(); serializer_class = ReasonSerializer; permission_classes = [IsAuthenticated]
class CustomStatusViewSet(viewsets.ModelViewSet): queryset = CustomStatus.objects.all(); serializer_class = StatusSerializer; permission_classes = [IsAuthenticated]
class SettlementStatusViewSet(viewsets.ModelViewSet): queryset = SettlementStatus.objects.all(); serializer_class = SettlementStatusSerializer; permission_classes = [IsAuthenticated]
class SalesProductViewSet(viewsets.ModelViewSet): queryset = SalesProduct.objects.all(); serializer_class = SalesProductSerializer; permission_classes = [IsAuthenticated]
class ConsultationLogViewSet(viewsets.ModelViewSet): queryset = ConsultationLog.objects.all(); serializer_class = LogSerializer; permission_classes = [IsAuthenticated]
class AdChannelViewSet(viewsets.ModelViewSet): queryset = AdChannel.objects.all(); serializer_class = AdChannelSerializer; permission_classes = [IsAuthenticated]
class BankViewSet(viewsets.ModelViewSet): queryset = Bank.objects.all(); serializer_class = BankSerializer; permission_classes = [IsAuthenticated]

class CallPopupView(APIView):
    permission_classes = [AllowAny] 
    def post(self, request):
        phone = clean_phone(request.data.get('phone')) 
        if not phone: return Response({'message': '전화번호가 없습니다.'}, status=400)
        customer = Customer.objects.filter(phone=phone).first()
        customer_name = customer.name if customer else "신규문의"
        print(f"📞 [전화 수신] {customer_name} ({phone})")
        return Response({'status': 'success', 'customer_name': customer_name, 'customer_id': customer.id if customer else None, 'message': 'PC 팝업 요청 확인'}, status=200)

class CallRecordSaveView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        phone = clean_phone(request.data.get('phone'))
        file_link = request.data.get('file_link') 
        if not phone or not file_link: return Response({'message': '데이터 부족'}, status=400)
        customer = Customer.objects.filter(phone=phone).first()
        if not customer: customer = Customer.objects.create(phone=phone, name=f"미등록({phone[-4:]})", status='미통건', owner=None, upload_date=datetime.date.today())
        ConsultationLog.objects.create(customer=customer, writer=customer.owner, content=f"[자동저장] 통화 녹취 파일: {file_link}")
        print(f"💾 [녹음 저장] {customer.name} - 링크 저장 완료")
        return Response({'status': 'success', 'message': '녹음 파일 연결 완료'}, status=201)



class TodoTaskViewSet(viewsets.ModelViewSet):
    queryset = TodoTask.objects.all()
    serializer_class = TodoTaskSerializer

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)

    # 관리자용: 내가 지시한 업무 목록 조회
    @action(detail=False, methods=['get'])
    def assigned(self, request):
        # 내가 보낸 것 or 전체 공지
        tasks = TodoTask.objects.all().order_by('-created_at')
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

class CancelReasonViewSet(viewsets.ModelViewSet): 
    queryset = CancelReason.objects.all().order_by('-created_at')
    serializer_class = CancelReasonSerializer
    permission_classes = [IsAuthenticated]
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_stats(request): return Response({'message': 'Use /api/stats/advanced/ instead'})


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all().order_by('name')
    serializer_class = ClientSerializer