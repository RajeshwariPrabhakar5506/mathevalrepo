from flask import Flask, render_template, request, redirect, session, jsonify, url_for
import random, os
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import pandas as pd
import numpy as np
import dotenv
import os 

dotenv.load_dotenv()

app = Flask(__name__)
app.secret_key = '9b8f8943da62f50e4ef49a242ed05ee0'

# --- Domains (ensure JSON files exist) ---
DOMAINS = ['algebra', 'arithmetic', 'graphs', 'patterns']
QUESTION_DIR = 'questions'

def load_questions():
    bank = {}
    for domain in DOMAINS:
        path = os.path.join(QUESTION_DIR, f"{domain}.json")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                all_questions = json.load(f)
                selected = random.sample(all_questions, min(5, len(all_questions)))
                bank[domain] = selected
    return bank

question_data = load_questions()

# --- Google Sheets setup ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
from dotenv import load_dotenv
load_dotenv()

creds_path = os.getenv("GOOGLE_CREDS_FILE")
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)

client = gspread.authorize(creds)
sheet = client.open("matheval").sheet1

# --- Student Flow ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start-quiz', methods=['POST'])
def start_quiz():
    session['student'] = {
        'name': request.form['name'],
        'roll': request.form['roll'],
        'school_code': request.form['school_code']
    }
    return redirect('/quiz')

@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if request.method == "POST":
        name = request.form.get("name")
        rollno = request.form.get("rollno")
        school_code = request.form.get("school_code")

        question_data = load_questions()
        return render_template("quiz.html", question_data=question_data, name=name, rollno=rollno, school_code=school_code)

    if 'student' not in session:
        return redirect(url_for('home'))

    question_data = load_questions()
    return render_template("quiz.html",
                           question_data=question_data,
                           name=session['student']['name'],
                           rollno=session['student']['roll'],
                           school_code=session['student']['school_code'])

@app.route('/get-questions')
def get_questions():
    return question_data

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    form = request.form
    result = {'total':0, 'correct':0, 'incorrect':0, 'domains':{}, 'answers':[]}

    for key in form:
        if key.startswith("answer_"):
            _, domain, idx = key.split('_')
            user = form[key].strip().lower()
            corr = form.get(f"correct_{domain}_{idx}", "").strip().lower()
            q_text = form.get(f"question_{domain}_{idx}", "")
            entry = {
                'domain': domain,
                'question': q_text,
                'your_answer': user,
                'correct_answer': corr,
                'is_correct': user == corr
            }
            result['answers'].append(entry)

            result['total'] += 1
            d = result['domains'].setdefault(domain, {'total':0,'correct':0,'incorrect':0})
            d['total'] += 1
            if entry['is_correct']:
                result['correct'] += 1
                d['correct'] += 1
            else:
                result['incorrect'] += 1
                d['incorrect'] += 1

    session['result'] = result
    save_to_sheet(session['student'], result, form)
    return redirect('/result')

@app.route('/result')
def result():
    if 'result' not in session:
        return redirect('/')
    return render_template('result.html',
                           student=session['student'],
                           result=session['result'])

def save_to_sheet(student, result, form):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for key in form:
        if key.startswith("answer_"):
            _, domain, idx = key.split('_')
            sheet.append_row([
                ts,
                student['name'],
                student['roll'],
                student['school_code'],
                domain,
                idx,
                form.get(f"question_{domain}_{idx}", ""),
                form[key],
                form.get(f"correct_{domain}_{idx}", ""),
                "Correct" if form[key].strip().lower() == form.get(f"correct_{domain}_{idx}", "").strip().lower() else "Incorrect"
            ])

# --- Teacher Flow ---
TEACHER_EMAIL = "teacher@school.com"
TEACHER_PASSWORD = "pass123"

@app.route('/teacher-login', methods=['POST'])
def teacher_login():
    if request.form['email'] == TEACHER_EMAIL and request.form['password'] == TEACHER_PASSWORD:
        session['teacher'] = {
            'school_code': request.form['school_code']
        }
        return redirect('/teacher-dashboard')
    return "Invalid credentials", 401

@app.route('/teacher-dashboard')
def teacher_dashboard():
    return render_template('teacher.html', DOMAINS=DOMAINS)

@app.route('/get-domain-data', methods=['POST'])
def get_domain_data():
    data = request.get_json()
    domain = data.get('domain', '').lower()
    school = session.get('teacher', {}).get('school_code', '')
    rows = sheet.get_all_records()
    scores = {}

    for r in rows:
        if r.get('school_code') == school and r.get('domain', '').lower() == domain:
            key = f"{r['name']} ({r['roll']})"
            scores.setdefault(key, {'correct': 0, 'total': 0})
            scores[key]['total'] += 1
            if r.get('status') == 'Correct':
                scores[key]['correct'] += 1

    return jsonify([{'student': s, 'accuracy': round(v['correct']/v['total']*100,2)} for s, v in scores.items() if v['total'] > 0])

# ✅ Report JSON data for PDF export
@app.route('/get-report-data')
def get_report_data():
    school_code = session.get('teacher', {}).get('school_code', '')
    rows = sheet.get_all_records()
    df = pd.DataFrame(rows)
    df_filtered = df[df["school_code"] == school_code]

    report_data = []
    grouped = df_filtered.groupby(['name', 'roll', 'school_code', 'domain'])

    for (name, roll, school, domain), group in grouped:
        total = len(group)
        correct = sum(1 for r in group.to_dict('records') if r.get("status") == "Correct")
        accuracy = round((correct / total) * 100, 2) if total > 0 else 0

        report_data.append({
            "name": name,
            "roll": roll,
            "school_code": school,
            "domain": domain,
            "score": correct,
            "total": total,
            "accuracy": accuracy
        })

    def convert_types(obj):
        if isinstance(obj, dict):
            return {k: convert_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_types(item) for item in obj]
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj

    clean_data = convert_types(report_data)
    return jsonify(clean_data)

if __name__ == '__main__':
    app.run(debug=True)