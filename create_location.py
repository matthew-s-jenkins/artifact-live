"""
Quick script to create a location via API
Usage: python create_location.py "Location Name" "Description" "Storage"
"""
import requests
import sys

# You need to be logged in first, so we'll need your session cookie
# For now, let's just show you what to do in the browser console

location_name = sys.argv[1] if len(sys.argv) > 1 else "Switch Box 1"
description = sys.argv[2] if len(sys.argv) > 2 else "Storage box for keyboard switches"
location_type = sys.argv[3] if len(sys.argv) > 3 else "Storage"

print("=" * 60)
print("To create a location, open your browser console and run:")
print("=" * 60)
print(f"""
fetch('http://localhost:5000/api/locations', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    credentials: 'include',
    body: JSON.stringify({{
        name: '{location_name}',
        description: '{description}',
        location_type: '{location_type}'
    }})
}})
.then(r => r.json())
.then(d => console.log('Location created:', d))
.catch(e => console.error('Error:', e))
""")
print("=" * 60)
print("\nOr better yet, let me add a Location Management tab to the UI...")
