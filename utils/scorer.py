def evaluate_answers(answers):
    correct = {'Q1': '8', 'Q2': '5', 'Q3': '16'}
    score = 0
    for q, ans in correct.items():
        if answers.get(q) == ans:
            score += 1
    return score
