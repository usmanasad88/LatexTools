import os
import re
from google import genai
from google.genai import types

import json

BIB_FILE = "ProactivePaper/draft_references.bib"
CACHE_FILE = "url_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=4)

def find_entries(text):
    """Finds all BibTeX entries in the text."""
    pos = 0
    entries = []
    while True:
        start = text.find('@', pos)
        if start == -1:
            break
        
        # Check if it looks like a valid entry start (e.g., @article{...)
        brace_start = text.find('{', start)
        if brace_start == -1:
            pos = start + 1
            continue
            
        # Verify characters between @ and { are valid identifier characters
        entry_type = text[start+1:brace_start].strip()
        if not re.match(r'^[a-zA-Z]+$', entry_type):
            pos = start + 1
            continue

        # Find matching closing brace
        brace_count = 1
        i = brace_start + 1
        while i < len(text) and brace_count > 0:
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
            i += 1
        
        if brace_count == 0:
            entries.append((start, i, text[start:i]))
            pos = i
        else:
            # Unmatched brace, skip this @
            pos = start + 1
            
    return entries

def extract_metadata(entry_text):
    """Extracts title and author from entry text for query."""
    title_match = re.search(r'title\s*=\s*[{"{]*(.*?)[}"}]*,', entry_text, re.IGNORECASE | re.DOTALL)
    author_match = re.search(r'author\s*=\s*[{"{]*(.*?)[}"}]*,', entry_text, re.IGNORECASE | re.DOTALL)
    
    title = title_match.group(1) if title_match else ""
    author = author_match.group(1) if author_match else ""
    
    # Clean up whitespace
    title = re.sub(r'\s+', ' ', title).strip()
    author = re.sub(r'\s+', ' ', author).strip()
    
    return title, author

def get_url_from_gemini(entry_text):
    """Queries Gemini for the URL of the paper."""
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
    )
    
    model = "gemini-3-pro-preview"
    prompt = f"""Find a URL to download this paper. Return ONLY the URL. If no URL is found, return "NOT_FOUND".

{entry_text}
"""
    
    # Remove thinking config as it caused validation errors
    # generate_content_config = types.GenerateContentConfig(
    #     thinking_config=types.ThinkingConfig(
    #         thinking_level="HIGH",
    #     ),
    # )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            # config=generate_content_config,  # Removed config
        )
        
        full_text = response.text
        # Find the first http URL line
        url_match = re.search(r'(https?://[^\s]+)', full_text)
        if url_match:
            return url_match.group(1)
        return "NOT_FOUND"

    except Exception as e:
        print(f"  API Error: {e}")
        return "NOT_FOUND"

def main():
    if not os.path.exists(BIB_FILE):
        print(f"Error: {BIB_FILE} not found.")
        return

    # Load cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
    else:
        cache = {}

    with open(BIB_FILE, 'r') as f:
        content = f.read()

    entries = find_entries(content)
    # Process from the end to keep indices valid.
    # Note: To correctly modify the file content using indices, 
    # we should process in reverse order of file position.
    entries.reverse()

    for start, end, entry_text in entries:
        title, author = extract_metadata(entry_text)
        
        # Check if URL already exists in the file entry
        if re.search(r'url\s*=', entry_text, re.IGNORECASE):
            # Also update cache if missing so we know it has a URL
            if title not in cache:
                # Try to extract the existing URL just for completeness, or just mark as done
                existing_url_match = re.search(r'url\s*=\s*{(.*?)}', entry_text, re.IGNORECASE)
                if existing_url_match:
                    cache[title] = existing_url_match.group(1)
            continue

        # Check if we already found it in a previous run (in cache)
        if title in cache:
            url = cache[title]
            if url == "NOT_FOUND":
                print(f"Skipping cached NOT_FOUND: {title[:50]}...")
                continue
            print(f"Using cached URL for: {title[:50]}...")
        else:
            # Not in cache, query Gemini
            print(f"Querying for: {title[:50]}...")
            try:
                url = get_url_from_gemini(entry_text)
                cache[title] = url
                # Save cache immediately
                with open(CACHE_FILE, 'w') as f:
                    json.dump(cache, f, indent=4)
            except Exception as e:
                print(f"  Error querying Gemini: {e}")
                continue

        if url and url != "NOT_FOUND" and url.startswith("http"):
            print(f"  Adding URL: {url}")
            # Insert URL field before the closing brace
            last_brace_idx = entry_text.rfind('}')
            if last_brace_idx != -1:
                new_entry_text = entry_text[:last_brace_idx] + f', url = {{{url}}}\n' + entry_text[last_brace_idx:]
                # Replace in content (using original indices works because we are iterating in reverse)
                content = content[:start] + new_entry_text + content[end:]
                
                # Write to bib file immediately
                with open(BIB_FILE, 'w') as f:
                    f.write(content)
        else:
            print("  No URL found.")

    print("Done updating bib file.")
    #     f.write(content)
    print("Done updating bib file.")

if __name__ == "__main__":
    main()
