import os
import django
import pandas as pd

# 장고 설정 로드
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crm_system.settings")
django.setup()

from sales.models import Customer

def clean_money(value):
    try:
        if pd.isna(value) or str(value).strip() == '': return 0
        return int(str(value).replace(',', '').replace(' ', '').replace('원', ''))
    except:
        return 0

def run_import():
    print("🚀 데이터 강제 분리 저장 시작! (중복 번호도 다 살립니다)")

    # 1. 상담관리 파일 처리
    print("📂 [1/2] 상담관리 파일 처리 중...")
    try:
        df_consult = pd.read_csv("샘플 - 류미애 상담관리.csv", header=5)
        df_consult = df_consult.dropna(subset=['휴대폰번호']) 
        
        count = 0
        for idx, row in df_consult.iterrows():
            origin_phone = str(row['휴대폰번호']).strip()
            
            # ⭐️ 핵심 수정: 전화번호 뒤에 순서 번호를 붙여서 강제로 다르게 만듦
            # 예: 010-0000-0000_1, 010-0000-0000_2 ...
            unique_phone = f"{origin_phone}_{idx}" 

            Customer.objects.update_or_create(
                phone=unique_phone, # 여기가 바뀜!
                defaults={
                    'name': row.get('고객명', f'고객_{idx}'), # 이름 없으면 임시 이름
                    'platform': row.get('광고사/플랫폼', ''),
                    'upload_date': row.get('상담날짜', ''),
                    'status': row.get('상태값', '미통건'),
                    'callback_schedule': str(row.get('재통예정일자', '')) if pd.notna(row.get('재통예정일자')) else '',
                    'last_memo': row.get('상담내용', '')
                }
            )
            count += 1
        print(f"   ✅ 상담 데이터 {count}건 저장 완료!")
    except Exception as e:
        print(f"   ❌ 상담파일 에러: {e}")

    # 2. 접수관리 파일 처리
    print("📂 [2/2] 접수관리 파일 처리 중...")
    try:
        df_sales = pd.read_csv("샘플 - 류미애 접수관리.csv", header=4)
        df_sales = df_sales.dropna(subset=['휴대폰번호'])

        count = 0
        for idx, row in df_sales.iterrows():
            origin_phone = str(row['휴대폰번호']).strip()
            # 여기는 매칭이 안 될 수 있어서, 일단 테스트용으로 별도 저장합니다.
            unique_phone = f"{origin_phone}_sales_{idx}"

            Customer.objects.update_or_create(
                phone=unique_phone,
                defaults={
                    'name': row.get('성함', ''),
                    'platform': row.get('디비구분/플랫폼', ''),
                    'upload_date': row.get('접수날짜', ''),
                    'status': row.get('상태값', ''),
                    'product_info': row.get('가입상품 / 상담이력', ''),
                    'policy_amt': clean_money(row.get('정책', 0)),
                    'support_amt': clean_money(row.get('지원금', 0)),
                    'installed_date': row.get('설치편성/완료', ''),
                    'additional_info': row.get('추가내용(후처리)', '')
                }
            )
            count += 1
        print(f"   ✅ 접수 데이터 {count}건 저장 완료!")
    except Exception as e:
        print(f"   ❌ 접수파일 에러: {e}")

    print("\n🎉 완료! 이제 관리자 페이지에서 새로고침 해보세요!")

if __name__ == '__main__':
    run_import()