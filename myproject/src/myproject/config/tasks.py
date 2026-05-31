from crewai import Task

from myproject.config.agents import client_agent


client_task = Task(
    description="""
    Session company_id (if non-empty, use this companyId for all tools that accept company_id): {company_id}

    The user request is: {user_request}

    Decide the intent before choosing any tool.

    Items/products intent:
    Use get_items when the user asks for items/products/categories/inventory.
    If the user asks for main items / father items, call get_items with main_fathers=true.
    If the user asks for sub items / child items, call get_items with is_main=false.

    Units intent:
    Use get_units when the user asks for stock units or item units.

    Item descriptions / recipes intent:
    Use get_item_descriptions when the user asks for material recipes/descriptions.

    Supplier cards intent:
    Use get_supplier_cards when the user asks for supplier account cards.

    Invoice books intent:
    Use get_invoice_books when the user asks for invoice books / \u062f\u0641\u0627\u062a\u0631.
    For "\u0643\u0644 \u0627\u0644\u062f\u0641\u0627\u062a\u0631" or "\u0647\u0627\u062a \u0627\u0644\u062f\u0641\u0627\u062a\u0631", pass book_type="all" to call /api/InvType?companyId=...
    For "\u062f\u0641\u0627\u062a\u0631 \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a", pass book_type="sales" to call /api/InvType?InvType_Type=-.
    For "\u062f\u0641\u0627\u062a\u0631 \u0627\u0644\u0645\u0634\u062a\u0631\u064a\u0627\u062a", pass book_type="purchases" to call /api/InvType?InvType_Type=true.

    Client/account creation intent:
    Use create_client only when the user explicitly asks to create/add/register a new
    client/account and provides a client/account name. Do not use create_client for vague requests
    or item requests.

    Client/account search intent:
    Use get_client when the user asks to search/fetch/find an existing client/account.
    Search can be by account name OR phone number OR account code. Pass the value as query.

    Client/account by id intent:
    Use get_account_by_id when the user asks for one account by exact id.
    Examples: "account id 153", "get account 153", "\u0647\u0627\u062a \u0627\u0644\u062d\u0633\u0627\u0628 \u0631\u0642\u0645 153".
    Pass only the numeric id as account_id.

    Account list intent:
    - get_all_accounts_tree for all accounts / account tree
    - get_sub_accounts for sub accounts
    - get_sandouk_accounts for sandouk/cashbox accounts

    If the request is unclear, do not guess and do not call a tool. Return:
    {"status":"needs_clarification","message":"Please specify whether you want items, units, recipes, supplier cards, invoice books, create a client, search accounts, or list accounts."}

    Tool-call rules:
    - Pass only real JSON argument values to tools.
    - Never pass a tool schema, properties, title, type, or required list as Action Input.

    Return the final result clearly in JSON text.
    """,
    agent=client_agent,
    expected_output="A JSON response containing the requested operation result",
)
