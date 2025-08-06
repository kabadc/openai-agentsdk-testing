from __future__ import annotations
import asyncio
import redis
import datetime

from agents import Agent, HandoffOutputItem, ItemHelpers, MessageOutputItem, RunContextWrapper, Runner, TResponseInputItem, ToolCallItem, ToolCallOutputItem, function_tool, trace
from dotenv import load_dotenv
load_dotenv() 

from typing import List
from pydantic import BaseModel
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

available_parks = """
Name: Funland Park Id: 1
Name: Springland Park Id: 2
Name: Futureland Park Id: 3
Name: Sweetland Park Id: 4
Name: Sweetland Deluxe Park Id: 5
Name: Retroland Park Id: 10
"""
today= datetime.datetime.now()
additional_rules = """
ADDITIONAL RULES:
    All visits require at least 1 adult
    The visit dates the client provides should be after today
    Today's date is {today}
"""

class ShoppingItem(BaseModel):
    product_id: int
    name: str | None = None
    visit_date: str | None = None
    adults: int
    children: int

class ShoppingContext(BaseModel):
    currency: str
    shopping_cart: List[ShoppingItem] = []

@function_tool(
    use_docstring_info=True
)
async def add_to_cart(ctx: RunContextWrapper[ShoppingContext], id: int, name: str, visit_date: str, adults: int, children: int) -> str:
    """
    Adds a product to the shopping cart context
    Args:
        ctx: the current context
        id: the numeric product id
        name: the product's name
        visit_date: the product visit date in format YYYY-MM-DD
        adults: the number of adults visiting
        children: the number of children visiting
    """
    print('**********************************')
    print(id, visit_date, adults, children)
    try:
        newItem = ShoppingItem(product_id=id, adults=adults, children=children, visit_date=visit_date, name=name)
        ctx.context.shopping_cart.append(newItem)
    except Exception as e:
        print(e)
    return "Product added"

@function_tool(
    use_docstring_info=True
)
async def modify_product_in_cart(ctx: RunContextWrapper[ShoppingContext], id: int, visit_date: str, adults: int, children: int) -> str:
    """
    Modifies a product in the shopping cart context, we can only modify the visit date or the amount of adults or children visiting.
    Args:
        ctx: the current context
        id: the numeric product id
        name: the product's name
        visit_date: the product visit date in format YYYY-MM-DD
        adults: the number of adults visiting
        children: the number of children visiting
    """
    print('**********************************')
    print(id, visit_date, adults, children)
    try:
        for shop in ctx.context.shopping_cart:
            if (shop.product_id == id):
                shop.visit_date = visit_date
                shop.adults = adults
                shop.children = children
    except Exception as e:
        print(e)
    return "Product modified"

@function_tool(
    use_docstring_info=True
)
async def remove_from_cart(ctx: RunContextWrapper[ShoppingContext], id: int) -> str:
    """
    Removes a product from the shopping cart
    Args:
        ctx: the current context
        id: the numeric product id
    """
    try:
        ctx.context.shopping_cart = list(filter(lambda sc: sc.product_id != id, ctx.context.shopping_cart))
    except Exception as e:
        print(e)
    return "Product removed"

@function_tool(
    use_docstring_info=True
)
async def lookup_shopping_cart(ctx: RunContextWrapper[ShoppingContext]) -> List[ShoppingItem]:
    """
    Looks up the products currently added to the cart, returns a list with the following information for each product
    id: the product id,
    name: the product name,
    visit_date: the product's visit date in YYYY-MM-DD format
    adults: number of adults visiting
    children: number of children visiting
    """
    return ctx.context.shopping_cart

shopping_cart_agent = Agent[ShoppingContext](
    name="Reservation quote agent",
    handoff_description="A helpful agent that handles a client's shopping cart.",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    You are an agent in charge of the shopping cart for theme park ticket reservations. If you are speaking to a customer, you probably were transferred to from the triage agent.
    If you believe the client is not trying to make a reservation inform the triage agent you can't do any actions.
    Always use the lookup_shopping_cart tool to see what the customer currently has in their shopping cart.
    The products currently available for sale are the following ones:
    {available_parks}
    You're not allowed to give general information about the parks' features, let a different agent handle that.
    Use the following routines to support the customer.
    PARK RESERVATION ROUTINE:
    1.- Make sure we offer the park the client wants to reserve.
    If the park the client wants is not in this list offer the available ones
    If the client wants a ticket to sweetland alwats make sure if the mean Sweetland Park or Sweetland Deluxe Park
    If the park is already in the cart or a park is already in the cart for the selected date suggest using a diffent date and don't perform any other action.
    2.- Ask for the date of visit if not provided, it should specify the year, month and day
    3.- Ask for the number of adults and children visiting if not provided
    4.- Ask the client if they want to reserve the product and if so use the add_to_cart tool to add them to the cart
    PARK RESERVATION MODIFICATION ROUTINE:
    1.- Make sure the shopping cart has the item the client wants to modify
    2.- If the product is in the shopping cart apply the changes the client wants with the park modify_product_in_cart tool
    3.- Inform the triage agent if the action was succesful or not
    PARK REMOVAL ROUTINE:
    1.- Make sure the shopping cart has items and if not answer you can't do the action
    2.- If the product to be removed is currently in the shopping cart use the remove_from_cart tool to remove it
    3.- Inform the triage agent if the action was succesful or not
    CHECK CURRENT CART ROUTINE:
    1.- Use the lookup_shopping_cart tool to know the products currently in the cart
    2.- Inform the client about the products currently in the cart if any
    """,
    tools=[lookup_shopping_cart, add_to_cart, remove_from_cart, modify_product_in_cart],
)

class ProductPrice(BaseModel):
    '''
    Information about the price of a product
    currency: the ISO of the currency quoted
    total_amount: the total amount
    individual_adult_amount: the price for a single adult
    individual_children_amount: the price for a single children
    discount_resume: discounts applied to the price
    '''
    currency: str
    total_amount: float
    individual_adult_amount: float
    individual_children_amount: float
    discounts_resume: str

@function_tool(
    use_docstring_info=True
)
async def price_inquiry_tool(ctx: RunContextWrapper[ShoppingContext], park_id: int, visit_date: str, adults: int, children: int) -> ProductPrice:
    """
    Looks up the price for given product using the id, visit date, and the number of adults and children visiting
    PARAMS
    park_id: the park's id,
    visit_date: the product's visit date
    adults: number of adults visiting
    children: number of children visiting
    RETURNS
    An object with the total amount and a short description of discounts applied to the price
    """
    discount_resume = "15 percent discount because of the visit date"
    adultP=1000
    childrenP=500
    total_amount=adults*adultP + children*childrenP
    if (ctx.context.shopping_cart.__len__() > 0):
        total_amount *= 0.8
        discount_resume = "20 percent discount because of products in shopping cart"
    price = ProductPrice(
        currency=ctx.context.currency,
        total_amount=total_amount,
        individual_adult_amount=adultP,
        individual_children_amount=childrenP,
        discounts_resume=discount_resume
    )
    return price

@function_tool(
    use_docstring_info=True
)
async def promotion_inquiry_tool(park_id: int) -> List[str]:
    """
    Looks up promotions available either in general or for a given park
    PARAMS
    park_id: the park's numeric id if known
    """
    promotions = list()
    promotions.append("PROMOMEX coupon for 10 percent off for Mexican visitors")
    promotions.append("Presale discount for certain parks of up to 15 percent off if buying 21 days in advance")
    return promotions

@function_tool(
    use_docstring_info=True
)
async def park_information_tool(park_id: int) -> List[str]:
    """
    Looks up information for a particular park
    PARAMS
    park_id: the park_id's nnumeric id
    RETURNS
    A list of information about a particular park
    """
    features = list()
    features.append("Access to the pools")
    features.append("Giftshop")
    if (park_id == 10):
        features.append("A big Arcade full of old school cabinets")
    if (park_id == 4):
        features.append("Our signature giant chocolate fountain at the center of the park")
        features.append("Giftshops with sweets from around the world")
    if (park_id == 5):
        features.append("Our signature giant chocolate fountain at the center of the park")
        features.append("Giftshops with sweets from around the world")
        features.append("A guided journey through the history of chocolate")
        features.append("1 free meal per person at any of the restaurants")
    return features

@function_tool(
    use_docstring_info=True
)
async def general_information_tool(query: str) -> List[str]:
    """
    Looks up information about our theme parks given a query
    PARAMS
    query: the question or topic you want information about
    RETURNS
    A list of information about the question or topic
    """
    print(f'The query for the tool: {query}')
    info = list()
    info.append("No data available")
    return info

parks_information_agent = Agent[ShoppingContext](
    name="Parks information agent",
    handoff_description="A helpful agent that handles a client's questions about our theme parks.",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    You are an agent in charge of information about our theme parks. If you are speaking to a customer, you probably were transferred to from the triage agent.
    If you believe the client is not making inquiries about our theme parks inform the triage agent you can't do any actions.
    The parks available are the following ones:
    {available_parks}
    Use the following routines to support the customer.
    Always return to the triage agent after you're done
    PRICE INQUIRY ROUTINE
    1.- Make sure we offer the park the client wants to know the price of
    If the park the client wants is not in this list mention the available ones
    2.- Ask for the date of visit if not provided, it should specify the year, month and day
    3.- Ask for the number of adults and children visiting, if not provided default to 1 adult. The visit always has to have at least 1 adult
    4.- Use the price_inquiry_tool to obtain the price for the park, make sure to mention the discounts applied over the regular price
    5.- Offer the client the option to buy them via the agent if they are interested.
    PROMOTIONS INQUIRY ROUTINE
    1.- Check if the user wants promotions about a park in particular or just general promotions
    2.- Use the promotion_inquiry_tool to obtain currently running promotions
    PARK COMPARISON ROUTINE
    1.- You can only compare two parks at once, ask for them if not provided
    2.- Use the product_information tool to obtain information about each theme park
    3.- Use only the information provided by the tool to make the comparison between parks
    4.- Return a table with the similarities and differences between them
    GENERAL INFORMATION ROUTINE
    1.- Use the provided tools to obtain the information the client wants regarding our theme parks
    2.- Use only the information provided by the tools for answers, not your own knowledge
    3.- If the tools don't provide enough information to provide an answer suggest to contact our customer service calling the number 000-00-0000, or via whatsapp at 00-000-000-0001 instead
    """,
    tools=[price_inquiry_tool, promotion_inquiry_tool, park_information_tool, general_information_tool],
)

triage_agent = Agent[ShoppingContext](
    name="Triage Agent",
    handoff_description="A triage agent that can delegate a customer's request to the appropriate agent.",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX} "
        "You are a helpful triaging agent. You can use your tools to delegate questions to other appropriate agents."
        "If the user's input is unrelated to theme park reservations or pricing reply you can't help them"
        "Your available agents are:"
        "shopping_cart_agent - Handles the client wanting to buy tickets for the park and any information regarding the client's shopping cart"
        "parks_information_agent - Handles general information about our products as well as any questions related to prices"
        "If the agents can't help the user apologize and request a new input"
    ),
    handoffs=[
        shopping_cart_agent,
        parks_information_agent,
    ],
)

shopping_cart_agent.handoffs.append(triage_agent)
parks_information_agent.handoffs.append(triage_agent)

async def main():
    current_agent: Agent[ShoppingContext] = triage_agent
    input_items: list[TResponseInputItem] = []
    context = ShoppingContext(currency='MXN')
    
    #default_item = ShoppingItem(product_id=10, adults=1, children=0, visit_date='2025-12-25', name='Retroland Park')
    #context.shopping_cart.append(default_item)
    
    # r = redis.Redis(host='127.0.0.1', port=6379, db=0)
    
    # Normally, each input from the user would be an API request to your app, and you can wrap the request in a trace()
    # Here, we'll just use a random UUID for the conversation ID
    conversation_id = 'default-test'

    while True:
        user_input = input("Enter your message: ")
        with trace("Customer service", group_id=conversation_id):
            input_items.append({"content": user_input, "role": "user"})
            result = await Runner.run(current_agent, input_items, context=context)
            '''
            for new_item in result.new_items:
                agent_name = new_item.agent.name
                if isinstance(new_item, MessageOutputItem):
                    #print(f"{agent_name}: {ItemHelpers.text_message_output(new_item)}")
                    print(f"{agent_name}: {ItemHelpers.text_message_output(new_item)}")
                elif isinstance(new_item, HandoffOutputItem):
                    print(
                        f"Handed off from {new_item.source_agent.name} to {new_item.target_agent.name}"
                    )
                elif isinstance(new_item, ToolCallItem):
                    print(f"{agent_name}: Calling a tool")
                elif isinstance(new_item, ToolCallOutputItem):
                    print(f"{agent_name}: Tool call output: {new_item.output}")
                else:
                    print(f"{agent_name}: Skipping item: {new_item.__class__.__name__}")
            '''
            for new_item in result.new_items:
                if isinstance(new_item, MessageOutputItem):
                    print(f"{ItemHelpers.text_message_output(new_item)}")
            input_items = result.to_input_list()
            current_agent = result.last_agent
            print(f'*****************')
            print(f'Current shopping cart: {context.shopping_cart}')
            print(f'*****************')


if __name__ == "__main__":
    asyncio.run(main())
