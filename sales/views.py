import datetime
from django.contrib.auth import authenticate
from django.db.models import Sum, Count
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Customer, User, ConsultationLog, Platform, FailureReason
from .serializers import CustomerSerializer

# 1. 고객 명단 조회
@api_view(['GET'])
def get_customers(request):
    customers = Customer.objects.all().order_by('-created_at')
    serializer = CustomerSerializer(customers, many=True)
    return Response(serializer.data)

# 2. 로그인 기능
@api_view(['POST'])
def login_api(request):
    username = request.data.get('username')
    password = request.data.get('password')
    
    user = authenticate(username=username, password=password)
    
    if user is not None:
        return Response({
            'message': '로그인 성공!',
            'user_id': user.id,
            'username': user.username,
            'role': user.role
        })
    else:
        return Response({'message': '아이디 또는 비밀번호가 틀렸습니다.'}, status=400)

# 3. DB 배정 (상담사 개별 가져가기)
@api_view(['POST'])
def assign_customer(request, customer_id):
    user_id = request.data.get('user_id')
    
    try:
        customer = Customer.objects.get(id=customer_id)
        user = User.objects.get(id=user_id)
        
        if customer.owner is None:
            customer.owner = user
            customer.save()
            return Response({'message': f'{user.username}님에게 배정되었습니다!'})
        else:
            return Response({'message': '이미 다른 상담사가 선점했습니다.'}, status=400)
            
    except Exception as e:
        return Response({'message': str(e)}, status=500)

# 4. 고객 정보 수정 (PATCH)
@api_view(['PATCH'])
def update_customer(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
        serializer = CustomerSerializer(customer, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    except Customer.DoesNotExist:
        return Response({'message': '존재하지 않는 고객입니다.'}, status=404)

# 5. 상담 로그 추가
@api_view(['POST'])
def add_consultation_log(request, customer_id):
    try:
        user_id = request.data.get('user_id')
        content = request.data.get('content')

        if not user_id:
            return Response({'message': '로그인 정보(user_id)가 없습니다.'}, status=400)

        customer = Customer.objects.get(id=customer_id)
        user = User.objects.get(id=user_id)

        ConsultationLog.objects.create(customer=customer, writer=user, content=content)
        
        # 고객의 마지막 메모 업데이트
        customer.last_memo = content
        customer.save()
        
        return Response({'message': '상담 기록 저장 완료!'})

    except Exception as e:
        return Response({'message': f'서버 에러: {str(e)}'}, status=400)

# 6. 대량 업로드 (플랫폼 단가 자동 적용)
@api_view(['POST'])
def bulk_upload(request):
    data_list = request.data.get('customers', [])
    success_count = 0
    
    # 플랫폼 단가 정보 미리 로딩
    platform_map = {p.name: p.cost for p in Platform.objects.all()}
    
    for item in data_list:
        try:
            phone = str(item.get('phone')).strip()
            if not phone: continue
            
            p_name = item.get('platform', '')
            
            # 엑셀 단가 vs 설정 단가 우선순위 처리
            input_cost = int(item.get('ad_cost', 0) or 0)
            final_cost = input_cost if input_cost > 0 else platform_map.get(p_name, 0)

            last_memo = item.get('last_memo', '')

            Customer.objects.create(
                phone=phone,
                name=item.get('name', '이름없음'),
                platform=p_name,
                last_memo=last_memo,
                ad_cost=final_cost,
                upload_date=item.get('upload_date', ''),
                status='미통건'
            )
            success_count += 1

        except Exception as e:
            print(f"에러 발생: {e}")
            continue

    return Response({
        'message': f'총 {success_count}건 등록 완료! (플랫폼 단가 자동적용)',
        'success': success_count
    })

# 7. 관리자 대시보드 통계 (AS 승인건 제외)
@api_view(['GET'])
def get_dashboard_stats(request):
    today = datetime.date.today()
    current_month_str = today.strftime("%Y-%m") 
    
    month_customers = Customer.objects.filter(upload_date__startswith=current_month_str)
    
    # [핵심] AS 승인된 건은 통계에서 제외
    valid_customers = month_customers.filter(is_as_approved=False)
    
    total_db = valid_customers.count()
    
    success_list = ['접수완료', '개통완료', '해지진행']
    success_custs = valid_customers.filter(status__in=success_list)
    success_count = success_custs.count()
    
    success_rate = round((success_count / total_db * 100), 1) if total_db > 0 else 0
    total_ad_cost = valid_customers.aggregate(Sum('ad_cost'))['ad_cost__sum'] or 0
    
    total_revenue = 0
    for c in success_custs:
        total_revenue += (c.policy_amt - c.support_amt) * 10000
        
    net_profit = total_revenue - total_ad_cost

    # 상담원별 랭킹
    agents = User.objects.filter(role='AGENT')
    agent_stats = []
    
    for agent in agents:
        my_custs = valid_customers.filter(owner=agent)
        my_total = my_custs.count()
        my_success = my_custs.filter(status__in=success_list)
        my_count = my_success.count()
        
        my_revenue = 0
        for c in my_success:
            my_revenue += (c.policy_amt - c.support_amt) * 10000
            
        my_rate = round((my_count / my_total * 100), 1) if my_total > 0 else 0
        
        agent_stats.append({
            'name': agent.username,
            'total': my_total,
            'count': my_count,
            'revenue': my_revenue,
            'rate': my_rate
        })
    agent_stats.sort(key=lambda x: x['revenue'], reverse=True)

    # 상세 리스트
    details = []
    for c in valid_customers:
        revenue = (c.policy_amt - c.support_amt) * 10000 if c.status in success_list else 0
        profit = revenue - c.ad_cost
        
        details.append({
            'id': c.id,
            'upload_date': c.upload_date,
            'agent': c.owner.username if c.owner else '(미배정)',
            'name': c.name,
            'platform': c.platform,
            'status': c.status,
            'ad_cost': c.ad_cost,
            'policy': c.policy_amt,
            'support': c.support_amt,
            'revenue': revenue,
            'net_profit': profit
        })

    return Response({
        'month': current_month_str,
        'total_db': total_db,
        'success_count': success_count,
        'success_rate': success_rate,
        'total_ad_cost': total_ad_cost,
        'total_revenue': total_revenue,
        'net_profit': net_profit,
        'agent_stats': agent_stats,
        'details': details
    })

# 8. AS 요청 처리 (승인/반려)
@api_view(['POST'])
def handle_as_request(request, customer_id):
    action = request.data.get('action') # 'approve' or 'reject'
    
    try:
        customer = Customer.objects.get(id=customer_id)
        
        if action == 'approve':
            customer.is_as_approved = True 
            customer.status = 'AS승인' 
            customer.save()
            return Response({'message': '✅ AS 승인 완료! (통계 및 광고비에서 제외됨)'})
            
        elif action == 'reject':
            customer.is_as_approved = False
            customer.status = '미통건'
            customer.as_reason = ''
            customer.save()
            return Response({'message': '↩️ AS 반려됨. (DB 상태가 미통건으로 복구됨)'})
            
    except Customer.DoesNotExist:
        return Response({'message': '존재하지 않는 DB입니다.'}, status=404)

# 9. 상담사 관리 (조회/생성)
@api_view(['GET', 'POST'])
def manage_agents(request):
    if request.method == 'GET':
        agents = User.objects.filter(role='AGENT').order_by('-date_joined')
        data = []
        for a in agents:
            data.append({
                'id': a.id,
                'username': a.username,
                'last_login': a.last_login.strftime('%Y-%m-%d %H:%M') if a.last_login else '접속 기록 없음',
                'date_joined': a.date_joined.strftime('%Y-%m-%d')
            })
        return Response(data)

    elif request.method == 'POST':
        username = request.data.get('username')
        password = request.data.get('password')
        
        if User.objects.filter(username=username).exists():
            return Response({'message': '이미 존재하는 아이디입니다.'}, status=400)
            
        User.objects.create_user(username=username, password=password, role='AGENT')
        return Response({'message': '상담사 등록 완료!'})

# 10. 상담사 삭제
@api_view(['DELETE'])
def delete_agent(request, agent_id):
    try:
        user = User.objects.get(id=agent_id)
        user.delete()
        return Response({'message': '삭제되었습니다.'})
    except User.DoesNotExist:
        return Response({'message': '존재하지 않는 사용자입니다.'}, status=404)

# 11. 플랫폼 설정 관리
@api_view(['GET', 'POST', 'DELETE'])
def manage_platforms(request, platform_id=None):
    if request.method == 'GET':
        platforms = Platform.objects.all()
        data = [{'id': p.id, 'name': p.name, 'cost': p.cost} for p in platforms]
        return Response(data)

    elif request.method == 'POST':
        name = request.data.get('name')
        cost = request.data.get('cost')
        
        obj, created = Platform.objects.update_or_create(
            name=name,
            defaults={'cost': cost}
        )
        return Response({'message': f'{name} 설정이 저장되었습니다.'})

    elif request.method == 'DELETE':
        try:
            Platform.objects.get(id=platform_id).delete()
            return Response({'message': '삭제되었습니다.'})
        except:
            return Response({'message': '실패'}, status=400)

# 12. 실패 사유 관리
@api_view(['GET', 'POST', 'DELETE'])
def manage_failure_reasons(request, reason_id=None):
    if request.method == 'GET':
        reasons = FailureReason.objects.all()
        data = [{'id': r.id, 'reason': r.reason} for r in reasons]
        return Response(data)

    elif request.method == 'POST':
        reason_text = request.data.get('reason')
        if not reason_text:
            return Response({'message': '내용을 입력하세요.'}, status=400)
        
        FailureReason.objects.get_or_create(reason=reason_text)
        return Response({'message': '사유가 추가되었습니다.'})

    elif request.method == 'DELETE':
        try:
            FailureReason.objects.get(id=reason_id).delete()
            return Response({'message': '삭제되었습니다.'})
        except:
            return Response({'message': '존재하지 않습니다.'}, status=400)

# 13. 상담사 개인 통계
@api_view(['GET'])
def get_my_stats(request):
    user_id = request.query_params.get('user_id')
    
    if not user_id:
        return Response({'message': 'user_id가 필요합니다.'}, status=400)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'message': '존재하지 않는 사용자입니다.'}, status=404)

    today = datetime.date.today()
    current_month_str = today.strftime("%Y-%m")
    
    my_data = Customer.objects.filter(owner=user, upload_date__startswith=current_month_str)
    
    total_db = my_data.count()
    total_ad_cost = my_data.aggregate(Sum('ad_cost'))['ad_cost__sum'] or 0
    
    accept_list = ['접수완료', '개통완료', '해지진행']
    accepted_custs = my_data.filter(status__in=accept_list)
    accept_count = accepted_custs.count()
    
    accept_rate = round((accept_count / total_db * 100), 1) if total_db > 0 else 0
    
    accept_revenue = 0
    for c in accepted_custs:
        accept_revenue += (c.policy_amt - c.support_amt) * 10000
        
    installed_custs = my_data.filter(status='개통완료')
    installed_revenue = 0
    for c in installed_custs:
        installed_revenue += (c.policy_amt - c.support_amt) * 10000
        
    final_profit = accept_revenue - total_ad_cost

    fail_reasons = my_data.filter(status='실패').values('detail_reason').annotate(count=Count('id')).order_by('-count')
    cancel_reasons = my_data.filter(status='접수취소').values('detail_reason').annotate(count=Count('id')).order_by('-count')

    return Response({
        'month': current_month_str,
        'total_db': total_db,
        'accept_rate': accept_rate,
        'total_ad_cost': total_ad_cost,
        'accept_revenue': accept_revenue,
        'installed_revenue': installed_revenue,
        'final_profit': final_profit,
        'fail_reasons': fail_reasons,
        'cancel_reasons': cancel_reasons
    })

# 14. 모든 DB에 현재 설정된 플랫폼 단가 일괄 적용
@api_view(['POST'])
def apply_platform_costs(request):
    platforms = Platform.objects.all()
    total_updated = 0
    
    for p in platforms:
        updated_count = Customer.objects.filter(platform=p.name).update(ad_cost=p.cost)
        total_updated += updated_count
        
    return Response({'message': f'총 {total_updated}건의 데이터에 최신 광고 단가가 적용되었습니다!'})

# 15. [NEW] 관리자용 DB 일괄 배정 (이게 빠져서 에러가 났었습니다)
@api_view(['POST'])
def allocate_customers(request):
    customer_ids = request.data.get('customer_ids', [])
    agent_id = request.data.get('agent_id')
    
    if not customer_ids or not agent_id:
        return Response({'message': '선택된 DB나 상담사가 없습니다.'}, status=400)
        
    try:
        agent = User.objects.get(id=agent_id)
        # 선택된 ID들의 owner를 해당 상담사로 변경
        updated_count = Customer.objects.filter(id__in=customer_ids).update(owner=agent)
        
        return Response({'message': f'총 {updated_count}건이 {agent.username}님에게 배정되었습니다.'})
        
    except User.DoesNotExist:
        return Response({'message': '존재하지 않는 상담사입니다.'}, status=400)
    except Exception as e:
        return Response({'message': str(e)}, status=500)