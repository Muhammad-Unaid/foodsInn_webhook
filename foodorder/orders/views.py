from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from .menu_data import price_data
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
import threading
import json
import re

import google.generativeai as genai 
import os

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from dotenv import load_dotenv
import threading, time
from difflib import get_close_matches
from langdetect import detect


# ───── Load ENV ─────
load_dotenv()
#-----------------------Gemini API ko configure karta hai.--------
genai.configure(api_key="AIzaSyD2O9-NCQXiVv-L0EKX4bfGAoyaszvL7GY")


#global memory jaha website aur FAQ ka scraped data store hota hai----
website_cache = ""
faq_cache = ""

# --- 2. Scrapers & Cache --- start------------------------------------------
# --- website scraper --- ( Static HTML scrape karta hai (scripts/styles remove karke saara text return karta hai).)
def scrape_website(url: str)-> str:
    """Website ka full text scrape karega"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for script in soup(["script", "style"]):
            script.extract()

        text = soup.get_text(separator=" ")
        return " ".join(text.split())  # clean spaces
    except Exception as e:
        return f"⚠️ Error scraping website: {e}"
# --- website scraper ---end ------------

#-------------scrape faqs----------(Website ke FAQ page se Q/A pairs nikalta hai (headings + unke answers).)
def scrape_faqs(url: str) -> str:
    """
    Scrapes FAQs from FoodsInn FAQ page.
    Detects Q/A pairs from headings (h2, h3, h4, strong, b) and 
    their immediate next <p> or text sibling as the answer.
    Returns clean string for LLM.
    """
    try:
        resp = requests.get(url, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        faqs = []

        # Possible tags used for FAQ questions
        question_tags = soup.find_all(["h2", "h3", "h4", "strong", "b"])

        for q_tag in question_tags:
            question = q_tag.get_text(" ", strip=True)

            # Filters: skip irrelevant headings
            if not question or len(question) < 5:
                continue
            if "faq" in question.lower():
                continue

            # Answer = first <p> after question tag
            answer_tag = q_tag.find_next(["p", "div"])
            answer = answer_tag.get_text(" ", strip=True) if answer_tag else ""

            # Only keep if answer looks meaningful
            if len(answer) > 3:
                faqs.append(f"Q: {question}\nA: {answer}")

        return "\n\n".join(faqs) if faqs else "❌ FAQs not found while scraping."

    except Exception as e:
        return f"⚠️ Error scraping FAQs: {e}"
#-------------scrape faqs----------end----

#------------scrape dynamic website------ (Selenium + Chrome use karke dynamic (JS-based) website ka content load karke scrape karta hai.⚠️ Ye thoda heavy hai, isliye real-time query me use nahi hota, sirf cache fill karne ke liye.)
def scrape_dynamic_website(url: str) -> str:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)
    driver.get(url)

    try:
        # ✅ wait until BODY loads or any FAQ keyword is present
        WebDriverWait(driver, 12).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # thoda extra wait for JS content
    except Exception as e:
        print("⚠️ Page load wait failed:", e)

    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")

    # ✅ Clean scripts/styles
    for script in soup(["script", "style"]):
        script.extract()

    text = soup.get_text(separator=" ")
    return " ".join(text.split())
#------------scrape dynamic website------ end ----

#----------refresh cache---------- (Website aur FAQs ko scrape karke global website_cache aur faq_cache update karta hai.)
def refresh_cache():
    global website_cache, faq_cache
    try:
        # website_cache = scrape_website("https://foodsinn.co/")  
        # faq_cache = scrape_faqs("https://foodsinn.co/pages/frequently-asked-questions")
        
        website_cache = scrape_dynamic_website("https://foodsinn.co/")
        faq_cache = scrape_dynamic_website("https://foodsinn.co/pages/frequently-asked-questions")


        print("✅ Cache refreshed")
        print(f"Website cache length: {len(website_cache)} chars")
        print(f"FAQ cache length: {len(faq_cache)} chars")

        # Preview first 500 characters
        print("\nWebsite cache sample:", website_cache[:500])
        print("\nFAQ cache sample:", faq_cache[:500])

    except Exception as e:
        print("⚠️ Cache refresh failed:", e)

#----------refresh cache---------- end -------

# ✅ ab yaha safe hai
refresh_cache()

# -----------------Har 10 min me refresh----------(Background thread me har 10 min ke baad refresh_cache() run karta hai (data fresh banaye rakhne ke liye).)
def auto_refresh():
    while True:
        refresh_cache()
        time.sleep(86400)  # daily refresh
threading.Thread(target=auto_refresh, daemon=True).start()
# -----------------Har 10 min me refresh----------end---------

# --- 2. Scrapers & Cache --- end----------------------------------------------------



# --- 4. Gemini Query Functions ----------------start-----------------



def query_faq_direct(user_query):
    """
    Fast FAQ lookup (without Gemini).
    Uses fuzzy matching for closest question in faq_cache.
    """

    # Split cached FAQs
    faqs = faq_cache.split("\n\n")
    questions = [f.split("\nA:")[0].replace("Q: ", "").strip() 
                 for f in faqs if f.startswith("Q:")]

    # Case-insensitive matching
    questions_lower = [q.lower() for q in questions]
    match = get_close_matches(user_query.lower(), questions_lower, n=1, cutoff=0.5)

    if match:
        matched_q = questions[questions_lower.index(match[0])]
        for f in faqs:
            if f.startswith(f"Q: {matched_q}"):
                answer = f.split("\nA:")[1].strip()
                return f"{matched_q} → {answer}"

    return "❌ Ye info FAQs me available nahi hai."


#Yeh main function hai jo smartly decide karta hai:
#Pehle menu dict check kare
#Agar menu me na mile to FAQs cache check kar
#Agar FAQs me bhi na mile to website cache check kare
#Reply user ki language me deta hai.
#👉 Yehi aapka chatbot ka core intelligence hai.

#-----------smart query handler-----------

def smart_query_handler(user_query, menu_dict):
    """
    Fast + fallback approach:
    1. Direct FAQ fuzzy match (fast)
    2. Direct menu check
    3. Direct website keyword search
    4. If all fail → Gemini (with 3 sec timeout)
    """

    # ✅ Step 1: Direct FAQ fuzzy match
    faq_direct = query_faq_direct(user_query)
    if "❌" not in faq_direct:
        return faq_direct  # Found answer in FAQ cache

    # ✅ Step 2a: Direct price range query
    nums = [int(n) for n in re.findall(r"\d+", user_query)]
    if len(nums) >= 2:
        low, high = nums[0], nums[1]
        items_in_range = [
            f"{i['title']} – Rs.{i['price']}"
            for cat in menu_dict.values() for i in cat
            if low <= i['price'] <= high
        ]
        if items_in_range:
            return "Range ke items:\n" + "\n".join(items_in_range)

    # ✅ Step 2b: Direct item price lookup
    for cat_items in menu_dict.values():
        for item in cat_items:
            if item["title"].lower() in user_query.lower():
                return f"{item['title']} ki price Rs. {item['price']} hai."


    # ✅ Step 3: Website keyword search (basic)
    if user_query.lower() in website_cache.lower():
        # Return a small relevant snippet from website_cache
        idx = website_cache.lower().find(user_query.lower())
        snippet = website_cache[idx:idx+150]
        return f"Website info: {snippet}..."

    # ✅ Step 4: Gemini fallback (with 3 sec timeout)
    # prompt = (
    #     f"Menu:\n{chr(10).join([f'{i['title']} – Rs. {i['price']}' for cat in menu_dict.values() for i in cat])}\n\n"
    #     f"FAQs:\n{faq_cache}\n\n"
    #     f"Website:\n{website_cache[:3000]}\n\n"
    #     f"User Question: {user_query}\n\n"
    #     "Rules:\n"
    #     "- Answer from menu, FAQ, or website.\n"
    #     "- Reply in the same language as user.\n"
    #     "- If not found, reply: ❌ Info not available.\n"
    # )

    # Detect script for user query
    script_type = detect_script(user_query)

    if script_type == "roman":
        language_rule = "Reply ONLY in Roman Urdu (no Urdu script, no English sentences)."
    elif script_type == "urdu":
        language_rule = "Reply ONLY in Urdu script."
    else:
        language_rule = "Reply ONLY in English."

    # Prepare Gemini prompt with strict language rule
    menu_text = "\n".join([f"{i['title']} – Rs. {i['price']}" for cat in menu_dict.values() for i in cat])

    prompt = (
        f"Menu:\n{menu_text}\n\n"
        f"FAQs:\n{faq_cache}\n\n"
        f"Website:\n{website_cache[:3000]}\n\n"
        f"User Question: {user_query}\n\n"
        f"Rules:\n"
        f"- Answer from menu, FAQ, or website.\n"
        f"- {language_rule}\n"
        "- Keep reply short and natural.\n"
        "- If not found, reply: ❌ Info not available.\n"
    )


    resp = safe_llm_call(prompt, timeout=3)
    if resp and "❌" not in resp:
        return resp

    # ✅ Final fallback
    return "⚠️ Sorry, mujhe abhi iska exact jawab nahi mila. Please dobara poochhiye."


#-----------smart query handle ------ end -----


def detect_script(text):
    urdu_chars = re.compile(r'[\u0600-\u06FF]')  # Urdu Unicode range
    if urdu_chars.search(text):
        return "urdu"
    elif re.search(r'[a-zA-Z]', text):
        return "roman"  # assume Roman Urdu or English
    return "english"


#------(FAQs ke against sirf Gemini query karta hai. (Backup/debugging ke liye useful))
def query_gemini_with_faq(user_query, url):
    # faq_data = scrape_faqs(url)
    faq_data = faq_cache  # use cache directly
    prompt = (
        f"Website FAQs:\n{faq_data}\n\n"
        f"User asked: {user_query}\n\n"
       "👉 Rules:\n"
        "- Match user question with the most similar FAQ question above.\n"
        "- Always give the paired answer if question matches semantically.\n"
        "- Reply in the same language user used.\n"
        "- If nothing relevant found: ❌ Ye info FAQs me available nahi hai.(in the user's language)"
    )

    model = genai.GenerativeModel("gemini-1.5-flash")
    resp = model.generate_content(prompt)
    return resp.text.strip()

# ---------ask gemini---------(Ek generic Gemini call (free-style prompt ke liye). Mostly testing / debugging ke liye.)
def ask_gemini(prompt):
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content(prompt)
    return response.text
# --- 4. Gemini Query Functions ----------------end-----------------

import concurrent.futures

def safe_llm_call(prompt, timeout=4):
    model = genai.GenerativeModel("gemini-1.5-flash")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(lambda: model.generate_content(prompt).text)
        try:
            return future.result(timeout=timeout).strip()
        except concurrent.futures.TimeoutError:
            return "⚠️ Sorry, reply slow ho raha hai. Kripya dobara poochhiye."







cart = []

restaurant_manager_email = 'softcodix1@gmail.com'  # Manager's email
delivery_boy_email = '1aryankhan1100@gmail.com'  # Delivery boy's email

# --- 3. Helpers ---------------------start----------------------------
#----get_item_price(title)----------Menu (price_data) me se kisi item ka price return karta hai.--(Cart / order system ke liye useful).
def get_item_price(title):
    for category_items in price_data.values():
        for item in category_items:
            if item["title"].lower() == title.lower():
                return item["price"]
    return 0


# User ke input me agar numbers (low–high range) diye gaye hain, to us range ke andar ke menu items return karta hai.
def handle_price_range_query(user_input, menu_dict):
    numbers = re.findall(r"\d+", user_input)
    if len(numbers) >= 2:
        low, high = map(int, numbers[:2])  
        items_in_range = []
        for cat in menu_dict.values():
            for item in cat:
                if low <= item["price"] <= high:
                    items_in_range.append(f"{item['title']} (Rs. {item['price']})")
        
        if items_in_range:
            return "Range ke items:\n" + "\n".join(items_in_range)
        else:
            return "❌ Is price range me koi item available nahi hai."
    return None
from difflib import get_close_matches
# --- 3. Helpers --------------------------------- end----------------------------


@csrf_exempt
def webhook(request):
    global cart

    if request.method == 'POST':
        data = json.loads(request.body)
        intent = data['queryResult']['intent']['displayName']
        parameters = data['queryResult'].get('parameters', {})
        # parameters = data['queryResult']['parameters']
        user_input = data['queryResult']['queryText'].lower()
        user_input_lower = user_input.lower()
        print("___", user_input)

        reply = "⚠️ Sorry, samajh nahi paya."

        # If user says "no" (exactly), treat intent as NoIntent
        if user_input == "no":
            intent = "NoIntent"

        response_payload = {}

        yes_no_responses = ["yes", "no", "✔️ yes", "no"]


        if intent == "LLMQueryIntent":
            if "website" in user_input_lower or "foods inn" in user_input_lower:

                print("---- Website mode ----")
                # print("Scraped:", scrape_website(website_cache)[:300])
                print("Scraped:", website_cache[:300])


                # reply = query_gemini_with_website(user_input, WEBSITE_URL)
                reply = smart_query_handler(user_input, price_data)
            elif any(k in user_input_lower for k in ["cheap", "sasta", "kam", "low"]):
                # Cheapest
                all_items = [item for cat in price_data.values() for item in cat]
                cheapest = min(all_items, key=lambda x: x['price'])
                reply = f"{cheapest['title']} sab se sasta hai, Rs. {cheapest['price']} ka."

            elif any(k in user_input_lower for k in ["expensive", "mahanga", "high"]):
                # Most expensive
                all_items = [item for cat in price_data.values() for item in cat]
                expensive = max(all_items, key=lambda x: x['price'])
                reply = f"{expensive['title']} sab se mahanga hai, Rs. {expensive['price']} ka."

            elif "range" in user_input_lower or "between" in user_input_lower:
                # Custom price range
                nums = [int(n) for n in re.findall(r"\d+", user_input_lower)]
                if len(nums) >= 2:
                    low, high = nums[0], nums[1]
                    items_in_range = [
                        f"{i['title']} – Rs.{i['price']}"
                        for cat in price_data.values() for i in cat
                        if low <= i['price'] <= high
                    ]
                    reply = "\n".join(items_in_range) if items_in_range else "❌ Is range me item nahi mila."
                else:
                    # reply = query_gemini_with_menu(user_input, price_data)
                    reply = smart_query_handler(user_input, price_data)
            else:
                # reply = query_gemini_with_menu(user_input, price_data)
                 reply = smart_query_handler(user_input, price_data)

            response_payload = {
                "fulfillmentMessages": [
                    {"text": {"text": [reply]}}
                ]
            }
            return JsonResponse(response_payload)
        # 🌐 Website scraping + FAQ fallback
                
        elif intent == "Default Fallback Intent":
            reply = smart_query_handler(user_input, price_data)
            response_payload = {
                "fulfillmentMessages": [
                    {"text": {"text": [reply]}}
                ]
            }
            return JsonResponse(response_payload)



        # ───────────── Existing Bot Logic ─────────────

        # 🌟 Show categories
        elif intent == "ShowCategoriesIntent":
            categories = list(price_data.keys())
            response_payload = {
                "fulfillmentMessages": [
                    {"text": {"text": ["🍽️ Please select a category:"]}},
                    {
                        "payload": {
                            "richContent": [[
                                {
                                    "type": "chips",
                                    "options": [{"text": cat} for cat in categories],
                                }
                            ]]
                        }
                    },
                ]
            }

        # 👉 Show items from selected category
        elif intent == "SelectCategoryIntent":
            selected_category = parameters.get("category")
            items = price_data.get(selected_category, [])
            response_payload = {
                "fulfillmentMessages": [
                    {"text": {"text": [f"📋 Items in {selected_category}:"]}},
                    {
                        "payload": {
                            "richContent": [[
                                {
                                    "type": "chips",
                                    "options": [{"text": item["title"]} for item in items],
                                }
                            ]]
                        }
                    },
                ]
            }

        # 🛒 Add item to cart
        elif intent == "Item Selected" and user_input not in yes_no_responses:
            selected_item = parameters.get("menu_items", "").strip()
            if not selected_item:
                selected_item = user_input  # fallback to query text
            print("+++", selected_item)
            found = False

            for category_items in price_data.values():
                for item in category_items:
                    if item["title"].lower() == selected_item.lower():
                        price = item["price"]
                        cart.append(item["title"])
                        found = True
                        break
                if found:
                    break

            if found:
                response_payload = {
                    "fulfillmentMessages": [
                        {"text": {"text": [f"✅ {selected_item} added to your cart. Price: Rs. {price}. Would you like anything else?"]}},
                        {
                            "payload": {
                                "richContent": [[
                                    {
                                        "type": "chips",
                                        "options": [{"text": " ✔️ Yes"}, {"text": "No"}],
                                    }
                                ]]
                            }
                        },
                    ]
                }
            else:
                response_payload = {
                    "fulfillmentText": f"❌ Sorry, we couldn't find '{selected_item}'. Please try again."
                }

        # 🧺 Show cart summary
        elif intent == "NoIntent":
            print("Intent received:", intent)
            if not cart:
                response_payload = {"fulfillmentText": "🛒 Your cart is empty."}
            else:
                total_amount = 0
                item_list = ""

                message_lines = [f"🛒 Here's your cart:"]
                total_amount = 0

                for idx, item in enumerate(cart, start=1):
                    price = get_item_price(item)
                    total_amount += price
                    emoji = "🍽️"
                    if "burger" in item.lower():
                        emoji = "🍔"
                    elif "fries" in item.lower():
                        emoji = "🍟"
                    elif any(drink in item.lower() for drink in ["coke", "pepsi", "sprite", "drink"]):
                        emoji = "🥤"
                    message_lines.append(f"{idx}. {emoji} {item} (Rs. {price})")

                message_lines.append(f"💰 Total: Rs. {total_amount}")
                message_lines.append("❌ Want to remove any item? Reply with the item number.")

                response_payload = {
                    "fulfillmentMessages": [
                        {
                            "payload": {
                                "richContent": [[
                                    *[
                                        { "type": "info", "title": line }
                                        for line in message_lines if line.strip()
                                    ]
                                ]]
                            }
                        },
                        {
                            "payload": {
                                "richContent": [[
                                    {
                                        "type": "chips",
                                        "options": [
                                            {"text": "✅ Confirm Order"},
                                            {"text": "🔁 Start Again"}
                                        ]
                                    }
                                ]]
                            }
                        }
                    ]
                }

        elif intent == "DeleteItemFromCart":
            item_number = parameters.get("item_number")
            item_name = parameters.get("item_name")
            message_lines = []  # Using a list to build message parts

            if not cart:
                response_payload = {"fulfillmentText": "🛒 Your cart is already empty."}
            else:
                removed = None

                # Remove by number
                if item_number is not None:
                    try:
                        index = int(item_number) - 1
                        if 0 <= index < len(cart):
                            removed = cart.pop(index)
                            message_lines.extend([
                                "✅ Removed item:",
                                f"{int(item_number)}. {removed}",
                                ""  # Empty line for spacing
                            ])
                        else:
                            message_lines.append("⚠️ Invalid item number.")
                    except:
                        message_lines.append("⚠️ Invalid number input.")

                # Remove by item name
                elif item_name:
                    for i, item in enumerate(cart):
                        if item_name.lower() in item.lower():
                            removed = cart.pop(i)
                            message_lines.extend([
                                f"✅ Removed: {removed}",
                                ""  # Empty line for spacing
                            ])
                            break
                    else:
                        message_lines.append("⚠️ Item not found in cart.")

                # Recalculate and show updated cart
                if cart:
                    total = 0
                    cart_text = []
                    for idx, item in enumerate(cart, 1):
                        price = get_item_price(item)
                        total += price
                        emoji = "🍽️"
                        if "burger" in item.lower():
                            emoji = "🍔"
                        elif "fries" in item.lower():
                            emoji = "🍟"
                        elif any(drink in item.lower() for drink in ["coke", "pepsi", "sprite", "drink"]):
                            emoji = "🥤"
                        cart_text.append(f"{idx}. {emoji} {item} (Rs. {price})")

                    message_lines.extend([
                        "🧺 Updated Cart:",
                        *cart_text,
                        "",
                        f"💰 Total: Rs. {total}"
                    ])
                else:
                    message_lines.extend([
                        "",
                        "🧺 Your cart is now empty."
                    ])

                # Join with newlines (Dialogflow will respect single newlines better)
                message = "\n".join([line for line in message_lines if line.strip()])

                if "Your cart is now empty" in message:
                    chip_options = [{"text": "🔁 Start Again"}]
                else:
                    chip_options = [
                        {"text": "✅ Confirm Order"},
                        {"text": "🔁 Start Again"}
                    ]

                print(message)

                response_payload = {
                    "fulfillmentMessages": [
                        {
                            "payload": {
                                "richContent": [[
                                    *[
                                        { "type": "info", "title": line }
                                        for line in message_lines if line.strip()
                                    ]
                                ]]
                            }
                        },
                        {
                            "payload": {
                                "richContent": [[
                                    {
                                        "type": "chips",
                                        "options": chip_options
                                    }
                                ]]
                            }
                        }
                    ]
                }

               


        # 📧 Send email & clear cart
        elif intent == "OrderConfirmationIntent":
            name = parameters.get('name', '').strip()
            phone_raw = parameters.get('phone', '')
            phone = str(phone_raw).strip() if phone_raw is not None else ''
            email = parameters.get('email', '').strip()
            raw_address = parameters.get('address', '')
            if isinstance(raw_address, list):
                address = raw_address[0].strip() if raw_address else ''
            else:
                address = raw_address.strip()

                if not name:
                    print("name not found")
                    # Ask again for name without fallback
                    return JsonResponse({
                        "outputContexts": [
                            {
                                "name": f"{data['session']}/contexts/awaiting_user_details",
                                "lifespanCount": 5
                            }
                        ],
                        "fulfillmentMessages": [
                            {
                                "payload": {
                                    "richContent": [[
                                        {
                                            "type": "info",
                                            "title": "⚠️ I didn't catch your name. Please type your full name to continue."
                                        }
                                    ]]
                                }
                            }
                        ]
                    })

            print("+++", name)
            print("___", phone)
            print("---", email)
            print("///", raw_address)

            total_amount = 0
            priced_items = []

            for item in cart:
                price = get_item_price(item)
                total_amount += price
                priced_items.append(f"{item} (Rs. {price})")

            items_str = ", ".join(priced_items)
            item_list_html = "".join([f"<li>{item}</li>" for item in priced_items])
            
                # ✅ Prepare response payload first
            response_payload = {
                "fulfillmentText": f"📩 Thank you {name}, your order has been confirmed. A confirmation email has been sent to {email}. Our rider will contact you at: {phone} and deliver your order to: {address}."
            }

            print(f"\nsecond payload {response_payload}")

            # ✅ Immediately return chatbot response
            response = JsonResponse(response_payload)
            def send_emails():
                # HTML email content for manager + delivery boy
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{
                            background-color: #f4f4f4;
                            font-family: Arial, sans-serif;
                            padding: 20px;
                        }}
                        .container {{
                            background-color: #ffffff;
                            padding: 30px;
                            border-radius: 10px;
                            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                            max-width: 600px;
                            margin: 0 auto;
                        }}
                        h2 {{
                            color: #4CAF50;
                        }}
                        p {{
                            font-size: 16px;
                            color: #333333;
                            line-height: 1.6;
                        }}                  
                        ul {{
                            font-family: "Times New Roman", Times, serif;
                            font-size: 20px;
                            color: #333333;
                            line-height: 1.6;
                        }}
                        .footer {{
                            margin-top: 20px;
                            font-size: 14px;
                            color: #777777;
                        }}
                    </style>
                </head>
                <body>
                    <div style="max-width: 600px; margin: auto; font-family: Arial, sans-serif; background-color: #fce3e1; padding: 30px; border-radius: 10px; color: #333;">
                        <div style="text-align: center;">
                            <img src="https://foodsinn.co/_next/image?url=https%3A%2F%2Fconsole.indolj.io%2Fupload%2F1728388057-Foods-Inn-Original-Logo.png%3Fq%3D10&w=256&q=75" alt="FoodsInn Logo" width="100" style="margin-bottom: 20px; ">
                            <h2 style="color: #6B7564; font-size: 18px;">New Order Received!</h2>
                        </div>

                        <p><strong>Customer Name:</strong> {name}</p>
                        <p><strong>Phone Number:</strong> {phone}</p>
                        <p><strong>Email:</strong> <a href="mailto:{email}" style="color: #d32f2f;">{email}</a></p>
                        <p><strong>Delivery Address:</strong> {address}</p>

                        <hr style="margin: 20px 0;">

                        <h3 style="color: #6B7564; font-size: 16px;">Ordered Items:</h3>
                        <ul style="line-height: 1.6;">
                            {item_list_html}
                        </ul>

                        <div style="margin-top: 30px; background-color: #6B7564; color: #fff; padding: 15px; border-radius: 8px; text-align: center; font-size: 33px;">
                            <strong>Total Amount: Rs. {total_amount}</strong>
                        </div>

                        <p style="margin-top: 30px; text-align: center;">Dear {name} Thank you for your order our agent will contact your as soon as possible.</p>

                        <footer style="text-align: center; margin-top: 40px; font-size: 13px;">
                            Powered by <a href="#" style="color: #d32f2f; text-decoration: none;">FoodsInn</a> - Your Food Lover's!
                        </footer>
                    </div>
                </body>
                </html>
                """

                print("before all emails")
                msg = EmailMultiAlternatives(
                    subject="New Order Received",
                    body=f"Order from {name}: {items_str}. Total: Rs. {total_amount}",
                    from_email=settings.EMAIL_HOST_USER,
                    to=[restaurant_manager_email, delivery_boy_email],
                )
                msg.attach_alternative(html_content, "text/html")
                msg.send()

                print("\nafter 1st email")


                print(f"\nfirst payload {response_payload}")

                # HTML email for user confirmation
                user_html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{
                            background-color: #f4f4f4;
                            font-family: Arial, sans-serif;
                            padding: 20px;
                        }}
                        .container {{
                            background-color: #ffffff;
                            padding: 30px;
                            border-radius: 10px;
                            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                            max-width: 600px;
                            margin: 0 auto;
                        }}
                        h2 {{
                            color: #4CAF50;
                        }}
                        p {{
                            font-size: 16px;
                            color: #333333;
                            line-height: 1.6;
                        }}                  
                        ul {{
                            font-family: "Times New Roman", Times, serif;
                            font-size: 20px;
                            color: #333333;
                            line-height: 1.6;
                        }}
                        .footer {{
                            margin-top: 20px;
                            font-size: 14px;
                            color: #777777;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container" style="max-width: 600px; margin: auto; font-family: Arial, sans-serif; background-color: #fce3e1; padding: 30px; border-radius: 10px; color: #333;" >
                        <div style="text-align: center;">
                            <img src="https://foodsinn.co/_next/image?url=https%3A%2F%2Fconsole.indolj.io%2Fupload%2F1728388057-Foods-Inn-Original-Logo.png%3Fq%3D10&w=256&q=75" alt="FoodsInn Logo" width="100" style="margin-bottom: 20px; ">
                            <h2 style="color: #6B7564; font-size: 18px;">Your Order detail !</h2>
                        </div>

                        <h2>Thank You, {name}!</h2>
                        <p>🎉 Your order has been placed successfully.</p>
                        <p><strong>Customer Name:</strong> {name}</p>
                        <p><strong>Phone Number:</strong> {phone}</p>
                        <p><strong>Email:</strong> <a href="mailto:{email}" style="color: #d32f2f;">{email}</a></p>
                        <p><strong>Delivery Address:</strong> {address}</p>

                        <hr style="margin: 20px 0;">

                        <h3 style="color: #6B7564; font-size: 16px;">Ordered Items:</h3>
                        <ul style="line-height: 1.6;">
                            {item_list_html}
                        </ul>
                        <div style="margin-top: 30px; background-color: #6B7564; color: #fff; padding: 15px; border-radius: 8px; text-align: center; font-size: 33px;">
                            <strong>Total Amount: Rs. {total_amount}</strong>
                        </div>

                        <p>Dear {name} Thank you for your order 🚴 Our delivery agent will contact you shortly. Enjoy your meal!</p>

                        <footer style="text-align: center; margin-top: 40px; font-size: 13px;">
                            
                            Powered by <a href="#" style="color: #d32f2f; text-decoration: none;">FoodsInn</a> - Your Food Lover's!
                        </footer>
                    </div>
                </body>
                </html>
                """

                print("\nbefore 2nd email")
                user_msg = EmailMultiAlternatives(
                    subject="Your FoodsInn Order Confirmation",
                    body=f"Hi {name}, your order (Total Rs. {total_amount}) has been confirmed. You'll be contacted at {phone}.",
                    from_email=settings.EMAIL_HOST_USER,
                    to=[email],
                )
                user_msg.attach_alternative(user_html_content, "text/html")
                user_msg.send()
                print("\nafter 2nd email")
                
                


            # ✅ Start email sending in background
            threading.Thread(target=send_emails).start()

            # ✅ Clear cart after order is placed
            cart = []

                
                # response_payload = {
                #     "fulfillmentText": f"📩 Thank you {name}, your order has been confirmed. A confirmation email has been sent to {email}. Our rider will contact you at: {phone} and deliver your order to: {address}."
                # }

            print(f"\nsecond payload {response_payload}")


        elif "🔁 start again" in user_input.lower():
            cart = []  # clear the cart
            response_payload = {
                "fulfillmentMessages": [
                    {
                        "text": {
                            "text": [
                                "🧹 Your cart has been successfully cleared."
                            ]
                        }
                    },
                    {
                        "text": {
                            "text": [
                                "🔄 No worries, let's begin a fresh order!"
                            ]
                        }
                    },
                    {
                        "payload": {
                            "richContent": [
                                [
                                    {
                                        "type": "chips",
                                        "options": [
                                            
                                            {"text": "Menu"}
                                        ]
                                    }
                                ]
                            ]
                        }
                    }
                ]
            }

        # elif intent == "Default Fallback Intent":
        #     reply = query_gemini(user_input, price_data)
        #     return JsonResponse({   
        #         "fulfillmentMessages": [
        #             {"text": {"text": [reply]}}
        #         ]
        #     })
    

        # ❓ Unknown input
        else:
            #reply = query_gemini(user_input, price_data)
            reply = smart_query_handler(user_input, price_data)
            
            response_payload = {
                "fulfillmentMessages": [
                    {"text": {"text": [reply]}}
                ]
            }

        return JsonResponse(response_payload)

    return JsonResponse({"message": "Invalid request method"}, status=405)   
   