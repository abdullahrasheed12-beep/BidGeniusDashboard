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

@app.route('/api/jobs')
def get_indeed_jobs():
    """
    Fetch live job listings from Indeed RSS feed.
    Query parameters:
    - q: Search query (default: "marketing analyst")
    - l: Location (default: empty for all locations)
    """
    try:
        query = request.args.get('q', 'marketing analyst')
        location = request.args.get('l', '')
        
        from urllib.parse import quote_plus
        rss_url = f"https://rss.indeed.com/rss?q={quote_plus(query)}&l={quote_plus(location)}"
        
        app.logger.info(f"Fetching Indeed RSS feed: {rss_url}")
        feed = feedparser.parse(rss_url)
        
        if not feed or not feed.entries:
            return jsonify({
                'success': False,
                'error': 'No jobs found or unable to fetch feed',
                'jobs': []
            }), 404
        
        jobs = []
        for entry in feed.entries[:20]:
            try:
                pub_date = entry.get('published', 'N/A')
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date_formatted = datetime(*entry.published_parsed[:6]).strftime('%B %d, %Y')
                else:
                    pub_date_formatted = pub_date
                
                summary = entry.get('summary', 'No description available')
                if len(summary) > 200:
                    summary = summary[:200] + '...'
                
                job = {
                    'id': hash(entry.get('link', '')),
                    'title': entry.get('title', 'No Title'),
                    'link': entry.get('link', '#'),
                    'description': summary,
                    'summary': summary,
                    'published': pub_date_formatted,
                    'posted': pub_date_formatted,
                    'source': 'Indeed',
                    'budget': 'Contact employer',
                    'skills': []
                }
                jobs.append(job)
            except Exception as e:
                app.logger.error(f"Error parsing job entry: {str(e)}")
                continue
        
        return jsonify({
            'success': True,
            'count': len(jobs),
            'query': query,
            'location': location,
            'jobs': jobs
        })
    
    except Exception as e:
        app.logger.error(f"Error fetching Indeed jobs: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch Indeed jobs: {str(e)}',
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
