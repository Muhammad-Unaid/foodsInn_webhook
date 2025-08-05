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

               
        # 📋 Ask for user details
        # elif intent == "OrderConfirmationIntent":
        #     response_payload = {
        #         "fulfillmentText": "📋 Please provide your Full Name to confirm your order."
        #     }

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
            

        # ❓ Unknown input
        else:
            response_payload = {
                "fulfillmentText": "❓ I didn't understand. Kindly choose an option from the menu above or type 'Menu' to return to the main menu. 📋✨."
            }

        return JsonResponse(response_payload)

    return JsonResponse({"message": "Invalid request method"}, status=405)   
   