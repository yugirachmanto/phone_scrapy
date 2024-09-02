from flask import Flask, render_template, request
import requests
import re
import csv
from bs4 import BeautifulSoup
import io
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

app = Flask(__name__)

# Define the headers and HTML tags for Google Knowledge Panel scraping
headers_Get = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:49.0) Gecko/20100101 Firefox/49.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

html_tags = {
    'knowledge_panel': 'kp-blk knowledge-panel',
    'claimed': "Own this business?",
    'name': "kno-ecr-pt kno-fb-ctx",
    'phone': 'LrzXr zdqRlf kno-fv',
    'days': "kc:/location/location:hours",
    'address': "kc:/location/location:address",
    'website': "IzNS7c duf-h"
}

html_regexes = {
    'name': '<span>(.*)</span>',
    'phone': '<span>(.*?)</span>',
    'hours': '<td>(.*)</td>',
    'address': '<span class="LrzXr">(.*)</span>',
    'website': 'href="(.*?)"'
}

# Function to perform Google search
def google(q):
    s = requests.Session()
    q = '+'.join(q.split())
    url = 'https://www.google.com/search?q=' + q + '&ie=utf-8&oe=utf-8'
    r = s.get(url, headers=headers_Get)
    return r.text

# Function to extract data after a specific HTML tag using regex
def get_string_after_tag(string, tag, regex, distance):
    if tag not in string:
        return None

    index = string.find(tag)
    substr = string[index:index+distance]
    match = re.search(regex, substr)
    return match.group(1) if match else None

# Function to extract phone numbers starting with Malaysian country code (+60 or 60)
def get_phone(html):
    try:
        phone_patterns = [
            r"\+62[\d \-\(\)]+[\d]",  # Matches numbers starting with +60
            r"\+6 2[\d \-\(\)]+[\d]",  # Matches numbers starting with +6 0
            r"\+ 62[\d \-\(\)]+[\d]",  # Matches numbers starting with + 60
            r"62[\d \-\(\)]+[\d]",    # Matches numbers starting with 60
            r"6 2[\d \-\(\)]+[\d]",    # Matches numbers starting with 6 0
            r" 62[\d \-\(\)]+[\d]",    # Matches numbers starting with 60
        ]
        phones = []
        for pattern in phone_patterns:
            phones.extend(re.findall(pattern, html))
        return remove_duplicates(phones)
    except:
        return []

# Function to remove duplicates from a list
def remove_duplicates(x):
    return list(dict.fromkeys(x))

# Function to attempt scraping with additional contact URL suffixes
def attempt_scrape(original_url):
    contact_suffixes = ["contact-us", "contact", "contact.html", "contactus", "contact-us.html", "contactus.html"]
    for suffix in contact_suffixes:
        try:
            contact_url = original_url.rstrip('/') + '/' + suffix
            response = requests.get(contact_url)
            print(f'Scraping Contact URL: {response.url}')
            
            # Parse the HTML content
            soup = BeautifulSoup(response.text, 'lxml')
            text_content = soup.get_text()

            # Extract phone numbers
            phones = get_phone(text_content)

            if phones:
                return phones
        except Exception as e:
            print(f'Failed to scrape {contact_url}: {e}')

    # If no phone numbers found in contact URLs
    return ["Not Found"]

# Function to get phone number from Google Knowledge Panel
def get_knowledge_panel_phone(query):
    html_results = google(query)
    has_knowledge_panel = html_tags['knowledge_panel'] in html_results

    if has_knowledge_panel:
        phone_number = get_string_after_tag(html_results, html_tags['phone'], html_regexes['phone'], 200)
        return phone_number if phone_number else "Not Found"
    return "Not Found"

# Function to scrape phone numbers with timeout (10 seconds)
def scrape_url(original_url, company_name):
    try:
        if original_url:
            response = requests.get(original_url, timeout=10)  # Set a 10-second timeout
            print(f'Scraping URL: {response.url}')
            soup = BeautifulSoup(response.text, 'lxml')
            text_content = soup.get_text()
            phones = get_phone(text_content)

            if not phones:
                phones = attempt_scrape(original_url)

            return {'Website URL': original_url, 'Company Name': company_name, 'Phone Numbers': ', '.join(phones)}
        
        else:
            google_keyword = f"{company_name} Head Office"
            phone_number = get_knowledge_panel_phone(google_keyword)
            return {'Website URL': 'N/A', 'Company Name': company_name, 'Phone Numbers': phone_number}

    except requests.exceptions.Timeout:
        print(f"Request timed out for {original_url}, skipping.")
        return {'Website URL': original_url if original_url else 'N/A', 'Company Name': company_name, 'Phone Numbers': "Not Found"}

    except Exception as e:
        print(f'Failed to process {original_url if original_url else company_name}: {e}')
        return {'Website URL': original_url if original_url else 'N/A', 'Company Name': company_name, 'Phone Numbers': "Not Found"}

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        data = request.form['data'].strip()
        urls = []
        for line in data.split('\n'):
            parts = line.strip().split(',', 1)  # Split into 2 parts: URL and Company Name
            if len(parts) == 2:
                urls.append(parts)
            elif len(parts) == 1:
                urls.append(('', parts[0]))  # URL is empty, company name is provided
            else:
                print(f'Skipping invalid line: {line.strip()}')

        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(scrape_url, original_url, company_name): (original_url, company_name) for original_url, company_name in urls}
            for future in future_to_url:
                try:
                    result = future.result(timeout=10)  # Set 10 seconds as the max time for each task
                    results.append(result)
                except FutureTimeoutError:
                    original_url, company_name = future_to_url[future]
                    print(f"Processing of {original_url if original_url else company_name} took too long and was skipped.")
                    results.append({'Website URL': original_url if original_url else 'N/A', 'Company Name': company_name, 'Phone Numbers': "Not Found"})

        # Convert results to CSV format
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['Website URL', 'Company Name', 'Phone Numbers'])
        writer.writeheader()
        for result in results:
            writer.writerow(result)

        csv_data = output.getvalue()
        output.close()
        return render_template('index.html', results=csv_data)
    return render_template('index.html', results=None)

if __name__ == '__main__':
    app.run(debug=True)
