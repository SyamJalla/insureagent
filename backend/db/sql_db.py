import pandas as pd
import sqlite3
import numpy as np
from datetime import datetime, timedelta
import random

def connect_db(db_path):
    return sqlite3.connect(db_path)

def generate_sample_data(random_state=42):
    random.seed(random_state)
    np.random.seed(random_state)
    first_names = ['John', 'Jane']
    last_names = ['Smith', 'Johnson']
    customers = pd.DataFrame({
        'customer_id': [f'CUST{str(i).zfill(5)}' for i in range(1, 1001)],
        'first_name': [random.choice(first_names) for _ in range(1000)],
        'last_name': [random.choice(last_names) for _ in range(1000)],
        'email': [f'user{i}@example.com' for i in range(1, 1001)],
        'phone': ['555-000-0000' for _ in range(1000)],
        'date_of_birth': [datetime(1980, 1, 1) for _ in range(1000)],
        'state': ['CA' for _ in range(1000)]
    })
    policies = pd.DataFrame({
        'policy_number': [f'POL{str(i).zfill(6)}' for i in range(1, 1501)],
        'customer_id': [f'CUST{str(random.randint(1, 1000)).zfill(5)}' for _ in range(1500)],
        'policy_type': [random.choice(['auto', 'home', 'life']) for _ in range(1500)],
        'start_date': [datetime(2023, 1, 1) for _ in range(1500)],
        'premium_amount': [100.0 for _ in range(1500)],
        'billing_frequency': ['monthly' for _ in range(1500)],
        'status': ['active' for _ in range(1500)]
    })
    auto_policy_details = pd.DataFrame({
        'policy_number': policies['policy_number'],
        'vehicle_vin': ['VIN123' for _ in range(1500)],
        'vehicle_make': ['Toyota' for _ in range(1500)],
        'vehicle_model': ['Camry' for _ in range(1500)],
        'vehicle_year': [2020 for _ in range(1500)],
        'liability_limit': [50000 for _ in range(1500)],
        'collision_deductible': [500 for _ in range(1500)],
        'comprehensive_deductible': [500 for _ in range(1500)],
        'uninsured_motorist': [1 for _ in range(1500)],
        'rental_car_coverage': [1 for _ in range(1500)]
    })
    billing = pd.DataFrame({
        'bill_id': [f'BILL{str(i).zfill(6)}' for i in range(1, 5001)],
        'policy_number': [random.choice(policies['policy_number']) for _ in range(5000)],
        'billing_date': [datetime(2024, 1, 1) for _ in range(5000)],
        'due_date': [datetime(2024, 1, 15) for _ in range(5000)],
        'amount_due': [100.0 for _ in range(5000)],
        'status': ['pending' for _ in range(5000)]
    })
    payments = pd.DataFrame({
        'payment_id': [f'PAY{str(i).zfill(6)}' for i in range(1, 4001)],
        'bill_id': [random.choice(billing['bill_id']) for _ in range(4000)],
        'payment_date': [datetime(2024, 1, 1) for _ in range(4000)],
        'amount': [100.0 for _ in range(4000)],
        'payment_method': ['credit_card' for _ in range(4000)],
        'transaction_id': ['TXN123' for _ in range(4000)],
        'status': ['completed' for _ in range(4000)]
    })
    claims = pd.DataFrame({
        'claim_id': [f'CLM{str(i).zfill(6)}' for i in range(1, 301)],
        'policy_number': [random.choice(policies['policy_number']) for _ in range(300)],
        'claim_date': [datetime(2024, 1, 1) for _ in range(300)],
        'incident_type': ['collision' for _ in range(300)],
        'estimated_loss': [5000.0 for _ in range(300)],
        'status': ['submitted' for _ in range(300)]
    })
    return {
        'customers': customers,
        'policies': policies,
        'auto_policy_details': auto_policy_details,
        'billing': billing,
        'payments': payments,
        'claims': claims,
    }

def drop_and_create_tables(conn):
    cursor = conn.cursor()
    cursor.executescript('''
        DROP TABLE IF EXISTS claims;
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS billing;
        DROP TABLE IF EXISTS auto_policy_details;
        DROP TABLE IF EXISTS policies;
        DROP TABLE IF EXISTS customers;
        
        CREATE TABLE customers (customer_id VARCHAR(20) PRIMARY KEY, first_name VARCHAR(50), last_name VARCHAR(50), email VARCHAR(100), phone VARCHAR(20), date_of_birth DATE, state VARCHAR(20));
        CREATE TABLE policies (policy_number VARCHAR(20) PRIMARY KEY, customer_id VARCHAR(20), policy_type VARCHAR(50), start_date DATE, premium_amount DECIMAL(10,2), billing_frequency VARCHAR(20), status VARCHAR(20), FOREIGN KEY (customer_id) REFERENCES customers(customer_id));
        CREATE TABLE auto_policy_details (policy_number VARCHAR(20) PRIMARY KEY, vehicle_vin VARCHAR(50), vehicle_make VARCHAR(50), vehicle_model VARCHAR(50), vehicle_year INTEGER, liability_limit DECIMAL(10,2), collision_deductible DECIMAL(10,2), comprehensive_deductible DECIMAL(10,2), uninsured_motorist BOOLEAN, rental_car_coverage BOOLEAN, FOREIGN KEY (policy_number) REFERENCES policies(policy_number));
        CREATE TABLE billing (bill_id VARCHAR(20) PRIMARY KEY, policy_number VARCHAR(20), billing_date DATE, due_date DATE, amount_due DECIMAL(10,2), status VARCHAR(20), FOREIGN KEY (policy_number) REFERENCES policies(policy_number));
        CREATE TABLE payments (payment_id VARCHAR(20) PRIMARY KEY, bill_id VARCHAR(20), payment_date DATE, amount DECIMAL(10,2), payment_method VARCHAR(50), transaction_id VARCHAR(100), status VARCHAR(20), FOREIGN KEY (bill_id) REFERENCES billing(bill_id));
        CREATE TABLE claims (claim_id VARCHAR(20) PRIMARY KEY, policy_number VARCHAR(20), claim_date DATE, incident_type VARCHAR(100), estimated_loss DECIMAL(10,2), status VARCHAR(20), FOREIGN KEY (policy_number) REFERENCES policies(policy_number));
    ''')
    conn.commit()

def insert_data(conn, data):
    for table, df in data.items():
        df.to_sql(table, conn, if_exists='append', index=False)
    conn.commit()

def setup_insurance_database(data, db_path):
    conn = connect_db(db_path)
    drop_and_create_tables(conn)
    insert_data(conn, data)
    conn.close()
