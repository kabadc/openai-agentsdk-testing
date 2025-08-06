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
    Use the following routines to support the customer.
    PARK RESERVATION ROUTINE:
    1.- Make sure we offer the park the client wants to reserve.
    If the park the client wants is not in this list offer the available ones
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


triage_agent = Agent[ShoppingContext](
    name="Triage Agent",
    handoff_description="A triage agent that can delegate a customer's request to the appropriate agent.",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX} "
        "You are a helpful triaging agent. You can use your tools to delegate questions to other appropriate agents."
        "Only do 1 handoff per run"
        "If the user's input is unrelated to theme park reservations or pricing reply you can't help them"
        "Your available agents are:"
        "shopping_cart_agent - Handles product reservations and any information regarding the client's shopping cart"
        #"parks_information_agent - Handles general information about our products as well as park prices"
        ""
        "If the agents can't help the user apologize and request a new query"
    ),
    handoffs=[
        shopping_cart_agent,
        #parks_information_agent,
    ],
)

shopping_cart_agent.handoffs.append(triage_agent)

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
            for new_item in result.new_items:
                agent_name = new_item.agent.name
                if isinstance(new_item, MessageOutputItem):
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
            input_items = result.to_input_list()
            current_agent = result.last_agent
            print(result.context_wrapper.context)


if __name__ == "__main__":
    asyncio.run(main())