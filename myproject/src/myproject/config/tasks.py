from crewai import Task

from myproject.config.agents import client_agent

client_task = Task(
    description="""
    Session company_id (if non-empty, use this companyId for all tools that accept company_id): {company_id}

    The user request is: {user_request}

    Decide the intent before choosing any tool.

    Items/products intent:
    Use get_items when the user asks for items/products/categories/inventory.
    Arabic examples: "عايز الاصناف", "هات الاصناف", "الصنف", "المنتجات", "المخزون".
    English examples: "items", "products", "categories", "inventory".
    If the user asks for main items / father items / الاصناف الرئيسية, call get_items with
    main_fathers=true.
    If the user asks for sub items / child items / الاصناف الفرعية, call get_items with
    is_main=false.

    Units intent:
    Use get_units when the user asks for stock units or item units.
    Arabic examples: "عايز الوحدات", "هات الوحدات", "وحدات", "وحدة".
    English examples: "units", "item units".

    Item descriptions / recipes intent:
    Use get_item_descriptions when the user asks for material recipes/descriptions.
    Arabic examples: "وصفات المواد", "عايز وصفات المواد", "وصفات".
    English examples: "recipes", "material recipes", "item descriptions".

    Supplier cards intent:
    Use get_supplier_cards when the user asks for supplier account cards.
    Arabic examples: "بطاقة الموردون", "بطاقات الموردين", "الموردون".
    English examples: "supplier cards", "suppliers".

    Client/account creation intent:
    Use create_client only when the user explicitly asks to create/add/register a new
    client/account and provides a client/account name. Arabic examples: "سجل عميل",
    "ضيف حساب", "انشاء عميل". Do not use create_client for vague requests or item requests.

    Client/account search intent:
    Use get_client when the user asks to search/fetch/find an existing client/account.
    Search can be by account name OR phone number OR account code. Pass the value as query.

    Account list intent:
    - get_all_accounts_tree for all accounts / account tree
    - get_sub_accounts for sub accounts
    - get_sandouk_accounts for sandouk/cashbox accounts

    If the request is unclear, do not guess and do not call a tool. Return:
    {"status":"needs_clarification","message":"Please specify whether you want items, units, recipes, supplier cards, create a client, search accounts, or list accounts."}

    Tool-call rules:
    - Pass only real JSON argument values to tools.
    - Never pass a tool schema, properties, title, type, or required list as Action Input.

    Return the final result clearly in JSON text.
    """,
    agent=client_agent,
    expected_output="A JSON response containing the requested operation result",
)
