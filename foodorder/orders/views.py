from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from .menu_data import price_data
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

import json

cart = []



restaurant_manager_email = 'softcodix1@gmail.com'  # Manager's email
delivery_boy_email = '1aryankhan1100@gmail.com'  # Delivery boy's email


def get_item_price(title):
    for category_items in price_data.values():
        for item in category_items:
            if item["title"].lower() == title.lower():
                return item["price"]
    return 0

@csrf_exempt
def webhook(request):
    global cart

    if request.method == 'POST':
        data = json.loads(request.body)
        intent = data['queryResult']['intent']['displayName']
        parameters = data['queryResult']['parameters']
        user_input = data['queryResult']['queryText'].lower()
        print("___", user_input)
       
        # if "🔁 start again" in user_input:
        #     cart = []
        #     return JsonResponse({
        #         "fulfillmentText": "🔄 Your cart has been cleared. Let's start again! Please choose a category:"
        #     })

        # if "🔁 start again" in user_input.lower():
        #     cart = []  # clear the cart
        #     response_payload = {
        #         "fulfillmentMessages": [
        #             {
        #                 "text": {
        #                     "text": ["🔄 Your cart has been cleared. Let's start again!"]
        #                 }
        #             },
        #             {
        #                 "payload": {
        #                     "richContent": [
        #                         [
        #                             {
        #                                 "type": "chips",
        #                                 "options": [
        #                                     {"text": "🛒 Again Order"}
        #                                 ]
        #                             }
        #                         ]
        #                     ]
        #                 }
        #             }
        #         ]
        #     }





        # If user says "no" (exactly), treat intent as NoIntent
        if user_input == "no":
            intent = "NoIntent"

        response_payload = {}

        yes_no_responses = ["yes", "no", "✔️ yes", "no"]

        # 🌟 Show categories
        if intent == "ShowCategoriesIntent":
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

                for item in cart:
                    price = get_item_price(item)
                    total_amount += price
                    emoji = "🍽️"
                    if "burger" in item.lower():
                        emoji = "🍔"
                    elif "fries" in item.lower():
                        emoji = "🍟"
                    elif any(drink in item.lower() for drink in ["coke", "pepsi", "sprite", "drink"]):
                        emoji = "🥤"
                    item_list += f"- {emoji} {item} (Rs. {price})\n"

                response_payload = {
                    "fulfillmentMessages": [
                        {"text": {"text": ["🧺 Here's what you've selected:"]}},
                        {"text": {"text": [item_list]}},
                        {"text": {"text": [f"💰 Total: Rs. {total_amount}"]}},
                        {"text": {"text": ["Would you like to confirm your order?"]}},
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

                
               
        # 📋 Ask for user details
        elif intent == "OrderConfirmationIntent":
            response_payload = {
                "fulfillmentText": "📋 Please provide your Full Name to confirm your order."
            }

        # 📧 Send email & clear cart
        elif intent == "CollectOrderDetailsIntent":
            name = parameters.get('name', '').strip()
            phone = parameters.get('phone', '').strip()
            email = parameters.get('email', '').strip()
            raw_address = parameters.get('address', '')
            if isinstance(raw_address, list):
                address = raw_address[0].strip() if raw_address else ''
            else:
                address = raw_address.strip()

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

            msg = EmailMultiAlternatives(
                subject="New Order Received",
                body=f"Order from {name}: {items_str}. Total: Rs. {total_amount}",
                from_email=settings.EMAIL_HOST_USER,
                to=[restaurant_manager_email, delivery_boy_email, email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send()

            cart = []

            response_payload = {
                "fulfillmentText": f"📩 Thank you {name}, your order has been confirmed. A confirmation email has been sent to {email}. Our rider will contact you at: {phone} and deliver your order to: {address}."
            }

        # # 🔁 Reset cart
        # elif "🔁 start again" in user_input:
        #     cart = []
        #     response_payload = {
        #         "fulfillmentText": "🔄 Your cart has been cleared. You can start again by selecting items."
        #     }
                # 🔁 Reset cart
        # elif "🔁 start again" in user_input:
        #     cart = []
        #     response_payload = {
        #         "fulfillmentText": "🔄 Your cart has been cleared. You can start again by selecting items."
        #     }
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
            

        # ❓ Unknown input
        else:
            response_payload = {
                "fulfillmentText": "❓ I didn't understand. Please choose a valid menu item or say 'no'."
            }

        return JsonResponse(response_payload)

    return JsonResponse({"message": "Invalid request method"}, status=405)
    