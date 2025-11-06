import os
import json
import feedparser
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SESSION_SECRET', 'dev-secret-key-change-in-production')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.route('/')
def index():
    with open('data/jobs.json', 'r') as f:
        jobs = json.load(f)
    return render_template('index.html', jobs=jobs)

@app.route('/api/generate-proposal', methods=['POST'])
def generate_proposal():
    try:
        if not GEMINI_API_KEY:
            return jsonify({
                'error': 'GEMINI_API_KEY not configured. Please add your API key to the .env file.'
            }), 400
        
        data = request.json
        job_title = data.get('title', '')
        job_description = data.get('description', '')
        job_budget = data.get('budget', '')
        
        prompt = f"""You are an expert freelance proposal writer. Write a compelling, professional Upwork proposal for the following job.

Job Title: {job_title}

Job Description: {job_description}

Budget: {job_budget}

Write a personalized proposal that:
1. Directly addresses the client's needs
2. Highlights relevant experience and skills
3. Explains your approach to the project
4. Shows enthusiasm and professionalism
5. Includes a brief call-to-action
6. Is concise (200-300 words)

Do not include placeholder text like [Your Name] or generic statements. Write as if you are a skilled freelancer with relevant experience."""

        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        
        if not response or not hasattr(response, 'text') or not response.text:
            return jsonify({
                'error': 'Gemini API returned empty response. This may be due to safety filters or content blocks.'
            }), 400
        
        proposal_text = response.text
        
        return jsonify({
            'proposal': proposal_text,
            'success': True
        })
    
    except Exception as e:
        return jsonify({
            'error': f'Error generating proposal: {str(e)}'
        }), 500

@app.route('/api/generate-application', methods=['POST'])
def generate_application():
    """
    Generate a complete job application package including:
    - Cover letter tailored to job and resume
    - Interview questions based on job requirements
    - Answers to questions based on resume experience
    """
    try:
        if not GEMINI_API_KEY:
            return jsonify({
                'error': 'GEMINI_API_KEY not configured. Please add your API key to the .env file.'
            }), 400
        
        data = request.json
        job = data.get('job', {})
        resume = data.get('resume', '')
        
        if not resume:
            return jsonify({
                'error': 'Resume text is required'
            }), 400
        
        job_title = job.get('title', '')
        job_description = job.get('description', '')
        
        # Generate cover letter
        cover_letter_prompt = f"""You are an expert career coach. Write a compelling, professional cover letter for this job application.

Job Title: {job_title}

Job Description: {job_description}

Candidate's Resume:
{resume}

Write a personalized cover letter that:
1. Directly addresses the job requirements
2. Highlights relevant experience from the resume
3. Shows genuine interest in the role
4. Is professional yet personable
5. Is concise (250-350 words)

Write the cover letter in first person, ready to copy and paste. Do not include placeholders like [Date] or [Company Name]."""

        # Generate interview questions
        questions_prompt = f"""You are an expert interviewer. Based on this job description, generate 5 common interview questions that would likely be asked.

Job Title: {job_title}

Job Description: {job_description}

Generate 5 realistic interview questions that:
1. Focus on key skills and requirements from the job description
2. Are commonly asked in real interviews
3. Are specific to this role
4. Range from technical to behavioral

Return ONLY a JSON array of questions, like this:
["Question 1", "Question 2", "Question 3", "Question 4", "Question 5"]"""

        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Generate cover letter
        cover_response = model.generate_content(cover_letter_prompt)
        if not cover_response or not hasattr(cover_response, 'text') or not cover_response.text:
            return jsonify({
                'error': 'Failed to generate cover letter'
            }), 400
        
        cover_letter = cover_response.text
        
        # Generate questions
        questions_response = model.generate_content(questions_prompt)
        if not questions_response or not hasattr(questions_response, 'text') or not questions_response.text:
            return jsonify({
                'error': 'Failed to generate interview questions'
            }), 400
        
        # Parse questions from response with robust handling of markdown fences
        try:
            questions_text = questions_response.text.strip()
            
            # Remove markdown code fences if present (```json ... ``` or ``` ... ```)
            if questions_text.startswith('```'):
                # Find the first newline after opening fence
                first_newline = questions_text.find('\n')
                if first_newline != -1:
                    questions_text = questions_text[first_newline + 1:]
                # Remove closing fence
                if questions_text.endswith('```'):
                    questions_text = questions_text[:-3]
                questions_text = questions_text.strip()
            
            # Try to parse as JSON array
            if questions_text.startswith('[') and questions_text.endswith(']'):
                parsed_questions = json.loads(questions_text)
                # Validate that all entries are non-empty strings
                questions_list = [
                    q.strip() for q in parsed_questions 
                    if isinstance(q, str) and len(q.strip()) > 10
                ]
            else:
                # Fallback: parse line-by-line and filter garbage
                lines = [line.strip('- 0123456789."\'') for line in questions_text.split('\n')]
                questions_list = [
                    q for q in lines 
                    if q and len(q) > 10 and not q.lower().startswith('json')
                ]
            
            # If we still don't have good questions, use fallback
            if not questions_list or len(questions_list) < 3:
                raise ValueError("Insufficient valid questions parsed")
                
        except Exception as e:
            app.logger.warning(f"Question parsing failed: {str(e)}, using fallback questions")
            # Fallback questions
            questions_list = [
                "Tell me about your relevant experience for this role.",
                "What interests you about this position?",
                "Describe a challenging project you've worked on.",
                "What are your salary expectations?",
                "Where do you see yourself in 3 years?"
            ]
        
        # Generate answers for each question
        qa_pairs = []
        for question in questions_list[:5]:  # Limit to 5 questions
            answer_prompt = f"""You are helping a job candidate prepare for an interview. Based on their resume, generate a strong, concise answer to this interview question.

Interview Question: {question}

Candidate's Resume:
{resume}

Generate a professional, concise answer (2-3 sentences) that:
1. Directly answers the question
2. References specific experience from the resume when relevant
3. Is confident and professional
4. Uses first person ("I have...")

Return ONLY the answer text, no introduction or explanation."""

            answer_response = model.generate_content(answer_prompt)
            if answer_response and hasattr(answer_response, 'text') and answer_response.text:
                answer = answer_response.text.strip()
            else:
                answer = "Based on my experience outlined in my resume, I have the relevant skills and background for this aspect of the role."
            
            qa_pairs.append({
                'question': question,
                'answer': answer
            })
        
        return jsonify({
            'success': True,
            'cover_letter': cover_letter,
            'questions': qa_pairs
        })
    
    except Exception as e:
        app.logger.error(f"Error generating application: {str(e)}")
        return jsonify({
            'error': f'Error generating application: {str(e)}'
        }), 500

@app.route('/api/jobs')
def get_remote_jobs():
    """
    Fetch live job listings from remote job board RSS feeds.
    Query parameters:
    - source: Job board source (remotive, wwremote, or all)
    """
    try:
        source = request.args.get('source', 'all')
        
        jobs = []
        
        # Remotive.io RSS feed
        if source in ['remotive', 'all']:
            try:
                app.logger.info("Fetching Remotive.io RSS feed")
                remotive_url = "https://remotive.com/api/remote-jobs/feed"
                feed = feedparser.parse(remotive_url)
                
                for entry in feed.entries[:15]:
                    try:
                        pub_date = entry.get('published', 'N/A')
                        pub_date_obj = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            pub_date_obj = datetime(*entry.published_parsed[:6])
                            pub_date_formatted = pub_date_obj.strftime('%B %d, %Y')
                        else:
                            pub_date_formatted = pub_date
                        
                        summary = entry.get('summary', 'No description available')
                        if len(summary) > 250:
                            summary = summary[:250] + '...'
                        
                        # Extract job type and location from title or description
                        title = entry.get('title', 'No Title')
                        job_type = 'Full-time'
                        location = 'Remote'
                        
                        if 'part-time' in title.lower() or 'part time' in summary.lower():
                            job_type = 'Part-time'
                        if 'contract' in title.lower() or 'freelance' in title.lower():
                            job_type = 'Contract'
                        
                        job = {
                            'id': hash(entry.get('link', '')),
                            'title': title,
                            'link': entry.get('link', '#'),
                            'description': summary,
                            'summary': summary,
                            'published': pub_date_formatted,
                            'published_date': pub_date_obj.isoformat() if pub_date_obj else None,
                            'posted': pub_date_formatted,
                            'source': 'Remotive',
                            'budget': 'See job posting',
                            'job_type': job_type,
                            'location': location,
                            'skills': []
                        }
                        jobs.append(job)
                    except Exception as e:
                        app.logger.error(f"Error parsing Remotive entry: {str(e)}")
                        continue
            except Exception as e:
                app.logger.error(f"Error fetching Remotive feed: {str(e)}")
        
        # We Work Remotely RSS feed
        if source in ['wwremote', 'all']:
            try:
                app.logger.info("Fetching We Work Remotely RSS feed")
                wwr_url = "https://weworkremotely.com/remote-jobs.rss"
                feed = feedparser.parse(wwr_url)
                
                for entry in feed.entries[:15]:
                    try:
                        pub_date = entry.get('published', 'N/A')
                        pub_date_obj = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            pub_date_obj = datetime(*entry.published_parsed[:6])
                            pub_date_formatted = pub_date_obj.strftime('%B %d, %Y')
                        else:
                            pub_date_formatted = pub_date
                        
                        summary = entry.get('summary', 'No description available')
                        if len(summary) > 250:
                            summary = summary[:250] + '...'
                        
                        title = entry.get('title', 'No Title')
                        job_type = 'Full-time'
                        location = 'Anywhere'
                        
                        if 'part-time' in title.lower() or 'part time' in summary.lower():
                            job_type = 'Part-time'
                        if 'contract' in title.lower() or 'freelance' in title.lower():
                            job_type = 'Contract'
                        
                        job = {
                            'id': hash(entry.get('link', '') + 'wwr'),
                            'title': title,
                            'link': entry.get('link', '#'),
                            'description': summary,
                            'summary': summary,
                            'published': pub_date_formatted,
                            'published_date': pub_date_obj.isoformat() if pub_date_obj else None,
                            'posted': pub_date_formatted,
                            'source': 'We Work Remotely',
                            'budget': 'See job posting',
                            'job_type': job_type,
                            'location': location,
                            'skills': []
                        }
                        jobs.append(job)
                    except Exception as e:
                        app.logger.error(f"Error parsing WWR entry: {str(e)}")
                        continue
            except Exception as e:
                app.logger.error(f"Error fetching WWR feed: {str(e)}")
        
        if not jobs:
            return jsonify({
                'success': False,
                'error': 'No jobs found from any source',
                'jobs': []
            }), 404
        
        # Sort by publish date (newest first)
        jobs.sort(key=lambda x: x.get('published_date') or '', reverse=True)
        
        return jsonify({
            'success': True,
            'count': len(jobs),
            'source': source,
            'jobs': jobs
        })
    
    except Exception as e:
        app.logger.error(f"Error fetching remote jobs: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch jobs: {str(e)}',
            'jobs': []
        }), 500

@app.route('/callback')
def oauth_callback():
    """
    OAuth callback route for Upwork integration.
    This endpoint handles the OAuth redirect from Upwork after user authorization.
    
    Expected query parameters:
    - code: Authorization code from Upwork
    - state: State parameter for CSRF protection
    
    Callback URL to configure in Upwork API settings:
    https://bid-genius-dashboard.vercel.app/callback
    """
    try:
        code = request.args.get('code')
        state = request.args.get('state')
        
        print("=" * 60)
        print("UPWORK OAUTH CALLBACK RECEIVED")
        print("=" * 60)
        print(f"Authorization Code: {code}")
        print(f"State Parameter: {state}")
        print(f"Full Query String: {request.query_string.decode('utf-8')}")
        print("=" * 60)
        
        if not code:
            return jsonify({
                'success': False,
                'error': 'Missing authorization code'
            }), 400
        
        app.logger.info(f"OAuth callback received - Code: {code[:10]}..., State: {state}")
        
        return redirect(url_for('index'))
        
    except Exception as e:
        app.logger.error(f"Error in OAuth callback: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'OAuth callback error: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
