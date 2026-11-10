"""What each KPI tile measures, shown when the pointer rests on the tile.

One glossary for the whole dashboard, keyed by the tile's label, so a tile
explains itself wherever it appears without each page spelling it out.
install() makes every st.metric / column.metric pick up its entry; a tile
that passes its own help (the weighted score cards do) keeps that. lib/style
stretches the hover area over the whole tile and hides the ⓘ icon, so the
explanation shows on hovering the tile itself.

Labels that change with the data ("Missed 03 Nov") are matched by pattern in
_PATTERNS; a label with no entry simply has no hover text.
"""
from __future__ import annotations

import re

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

GLOSSARY = {
    # ---- sales, revenue, orders
    "Revenue": "Sales in KES, refunds netted and delivery fees left out; other currencies converted at each order's own rate.",
    "Sales Made": "What the shop attendants and BAs sold in the range, in KES: refunds netted, delivery fees out — counted like the Sales page.",
    "Total Revenue": "All sales in the range, in KES, refunds netted.",
    "Orders": "Number of separate till orders (receipts) in the range.",
    "Units Sold": "Number of items sold, net of refunds.",
    "Bags Sold": "Number of bags sold, net of refunds; combo containers aren't counted twice.",
    "Total Bags Sold": "Number of bags sold in the range, net of refunds.",
    "Target Achieved": "Revenue so far against the sales target for the same days.",
    "Corporate Revenue": "Sales to customers recorded as Corporate (company orders), in KES. For a shop it is scored against 10% of its revenue target.",
    "Overall Revenue (incl. Corporate)": "Shop and online revenue plus the corporate team's sales.",
    "Avg Order Value": "Revenue ÷ orders: the average value of one receipt.",
    "Basket Value": "Revenue ÷ orders — the average sale. Scored against KES 3,200.",
    "Basket Size": "Bags ÷ orders — how many bags an average sale has.",
    "Revenue per Attendant": "The shop's revenue ÷ the attendants and BAs who served there in the range.",
    "Delivery fee": "Delivery fees charged on orders; money, not a product, so left out of bags sold.",
    # ---- customers
    "Unique Customers": "Different customers who bought, counted by phone number (shop and staff numbers left out).",
    "Customers": "Different customers who bought, counted by phone number.",
    "Total Customers": "Different customers who bought, counted by phone number.",
    "Avg Spend / Customer": "Revenue ÷ unique customers: what one customer spent on average in the range.",
    "Avg Spend/Customer": "Revenue ÷ unique customers: what one customer spent on average in the range.",
    "Average per Customer": "Corporate revenue ÷ corporate customers.",
    "Repeat Rate": "Share of customers who bought on two or more different days in the range.",
    "Repeat Purchase": "Share of the shop's customers who bought on two or more different days in the range (two orders the same day are one visit).",
    "Retention": "Of the customers who bought at the shop in the previous period of the same length, the share who came back in this one.",
    "Data Quality": "Share of named customer sales with a valid phone number recorded.",
    "Individual": "Sales to individual shop customers (not corporate).",
    "Corporate Sales": "Jobs done by the corporate sales team, at their quoted value.",
    "Shop Corporate": "Corporate orders rung at the shop tills (customer recorded as Corporate).",
    "Revenue Shown": "Revenue for the channel picked above.",
    "Open Quotations": "Value of corporate quotations sent and not yet confirmed or cancelled.",
    # ---- products and offers
    "Masterfile": "Share of the bags sold that are on the product masterfile (the official catalogue).",
    "Masterfile Sales": "Sales value of products on the masterfile.",
    "Off-Catalog Sales": "Sales value of products not on the masterfile.",
    "% Masterfile": "Masterfile sales as a share of all sales value.",
    "Total Sales Value": "Value of everything sold in the range.",
    "Categories Sold": "Number of product categories with at least one sale.",
    "Top Category": "The category with the most bags sold.",
    "Bag Styles Sold": "Number of different bag styles (colours combined) sold.",
    "Power Deal Revenue": "Sales of this month's Power Deal bags at the deal price (below the bag's full price).",
    "Deal of the Week Revenue": "Sales of the current Deal of the Week bags (two-week Sun–Sat cycles) at the deal price.",
    "Running Combos": "Revenue from the combos set up as products in Odoo.",
    "Self-made Combos": "Revenue from bags sold together as a combo made up at the till.",
    "Self-made Share": "Self-made combos as a share of all combo revenue.",
    "Avg Bundle Price": "Average price of one combo.",
    "New Collections": "Bag styles launched recently (the new collections), selling in the range.",
    # ---- stock and dispatch
    "Stock Health": "Share of the shops' selling lines holding between the minimum and maximum days of cover.",
    "Out of Stock": "Stock: selling lines with none on hand. WhatsApp: chats where the bag asked for wasn't in stock.",
    "Below Min": "Selling lines with fewer days of cover than the minimum set above.",
    "Over Max": "Selling lines with more days of cover than the maximum set above.",
    "To Restock": "Bags needed to bring every line below the maximum back up to it.",
    "Excess": "Bags held above the maximum days of cover.",
    "Opening": "Stock at the shop at the end of the day before the range.",
    "Dispatched": "Bags sent from the warehouse to the shop in the range.",
    "Received": "Bags the shop confirmed receiving in the range.",
    "Sold": "Bags sold at the shop in the range.",
    "Closing": "Stock at the shop at the end of the range.",
    "Mismatched Lines": "Bags whose opening + received − sold doesn't add up to the closing stock — movements not explained.",
    "Bags Dispatched": "Bags sent from the warehouse to the shops in the range.",
    "Still in Transit": "Bags sent but not yet received at the shop.",
    "Bag Types": "Number of different bags dispatched.",
    "Most Dispatched": "The bag sent out most.",
    "Dispatched Without a Shop Request": "Bags sent to a shop that no shop request asked for.",
    "Arrived Outside Dispatch": "Bags that reached a shop without going through a warehouse dispatch.",
    "Fill Rate": "Bags dispatched ÷ bags the shops requested.",
    "Closed Unfilled": "Bags requested on requests that were closed without them being sent.",
    "Still Open": "Requests (or leads) not yet completed.",
    "Cancelled": "Requests cancelled.",
    "Total Units in Stock": "All units on hand across the locations shown.",
    "Locations Tracked": "Number of stock locations with stock.",
    "Products Tracked": "Number of different products in stock.",
    "Top Location": "The location holding the most units.",
    "Top 5 Share": "Share of bags sold that came from the 5 best-selling bags.",
    "Top 10 Share": "Share of bags sold that came from the 10 best-selling bags.",
    "Top 20 Share": "Share of bags sold that came from the 20 best-selling bags.",
    "Make Up 80% of Sales": "How many bags, best sellers first, it takes to reach 80% of the bags sold.",
    "Total Distributed": "Bags sent out from the hub in the range.",
    "To Shops & Channels": "Bags sent to the shops and sales channels.",
    "Bag Styles": "Number of different bag styles.",
    "Top Destination": "Where the most bags went.",
    "Total Dispatched": "Bags dispatched in the range.",
    "Product Families": "Number of bag families (styles, colours combined).",
    "Bag Styles Dispatched": "Number of different bag styles dispatched.",
    "Bags Sent": "Bags sent out in the range.",
    "Landed Next Day": "Bags received the day after they were sent.",
    "In Transit Now": "Bags on the way to Sinza and Uganda right now.",
    "Bag Styles Outstanding": "Bag styles with stock still in transit.",
    # ---- production
    "Materials Used": "Materials drawn from the store into production in the range.",
    "Bags Drawn": "Bags whose materials were drawn for cutting.",
    "Bags Cut": "Bags cut in the range.",
    "Bags Issued": "Cut bags issued to the tailors.",
    "WIP Created": "Bags put into work in progress (being made).",
    "Bags Cut in Store": "Cut bags waiting in the store now (today's stock, not the range).",
    "Repairs": "Bags sent for repair.",
    "Samples": "Sample bags made.",
    # ---- footfall
    "Walk-ins Counted": "People counted walking into the shops (entered daily by the shops).",
    "Purchased Walk-ins": "Walk-in sales at the tills (online, activation and staff orders left out).",
    "Didn't Buy": "Walk-ins counted − walk-ins who bought.",
    "Walk-in Conversion": "Walk-ins who bought ÷ walk-ins counted, on the days a count was entered.",
    "Revenue per Walk-in": "Walk-in revenue ÷ walk-ins counted.",
    "Online Orders": "Orders that came in online (website, WhatsApp deliveries) — not walk-ins.",
    "Activation & Employee": "Orders from activations and staff purchases — not walk-ins.",
    "Refunds": "Refund receipts in the range.",
    "Days Not Counted": "Shop-days with walk-in sales but no walk-in count entered.",
    "Undercounted Days": "Shop-days with more purchases than walk-ins counted — the count was too low.",
    # ---- WhatsApp, social DMs, leads
    "Interactions": "WhatsApp chats logged in the WhatsApp Monitor.",
    "Purchased": "Chats or leads that ended in a sale.",
    "Transferred": "Chats passed to another branch to serve.",
    "First Response": "Average minutes to the first reply on a WhatsApp chat (target 3 minutes).",
    "Out-of-Stock Interactions": "Chats where the customer asked for a bag that wasn't in stock.",
    "Products Asked For": "Different bags customers asked for that were out of stock.",
    "Most Wanted": "The out-of-stock bag asked for most.",
    "Branches Affected": "Branches with at least one out-of-stock chat.",
    "Follow-ups Recorded": "Follow-up calls or messages recorded on earlier chats.",
    "Bought": "Followed-up customers who went on to buy.",
    "Still Interested": "Followed-up customers who said they'll buy later or visit the shop.",
    "Not Reachable": "Follow-ups where the customer couldn't be reached.",
    "Feedback Links Sent": "Feedback form links sent to customers from WhatsApp.",
    "Purchase Links": "Feedback links sent after a purchase.",
    "Enquiry Links": "Feedback links sent after an enquiry.",
    "Walk-in Links": "Feedback links sent to walk-in customers.",
    "Locations Sending": "Branches that sent at least one feedback link.",
    "Transferred Out": "Chats this branch passed to another.",
    "Linked to Destination": "Transfers linked to the chat at the branch that received them.",
    "Needs Destination Link": "Transfers not yet linked to the receiving branch's chat, so their outcome is unknown.",
    "Bought at Destination": "Transferred customers who bought at the branch they were sent to.",
    "Transferred In": "Chats passed to this branch by another.",
    "Social DMs": "Direct messages logged from Instagram, Facebook, TikTok and X.",
    "Converted": "DMs that ended in a sale.",
    "From Ads": "DMs that came from a paid ad.",
    "Awaiting a Call": "DMs waiting for their first or second follow-up call.",
    "Sent to a Branch": "DMs passed to a branch to serve.",
    "Leads Captured": "Walk-in leads recorded at the shops (customers who visited and didn't buy).",
    "Awaiting Stock": "Leads waiting for a bag to come back in stock.",
    "Lost": "Leads closed without a sale.",
    "Follow-ups Due": "Open leads whose follow-up date has come.",
    "Overdue a Week+": "Follow-ups more than a week past their date.",
    "Open, No Follow-up Date": "Open leads with no follow-up date set.",
    "Locations": "Number of shops in the list.",
    "Bags": "Number of bags in these orders.",
    "Out-of-Stock Requests": "Customers who asked for a bag that wasn't in stock — WhatsApp chats and walk-in leads together.",
    "Leads (walk-in)": "Out-of-stock requests from customers who visited a shop.",
    "WhatsApp (online)": "Out-of-stock requests that came in on WhatsApp.",
    "Bags Asked For": "Different bags asked for while out of stock.",
    "Fulfilled": "Requests where the customer later bought the bag they asked for.",
    "Fulfilment Rate": "Fulfilled ÷ out-of-stock requests.",
    "Bought Something Else": "Customers who bought a different bag instead.",
    "Still Waiting": "Requests where the customer hasn't bought yet.",
    "Days to Fulfil": "Median days from the request to buying the bag.",
    # ---- lead recycling
    "Unconverted Customers": "Customers (by phone) who got in touch in the window and didn't buy then.",
    "Recovered": "Unconverted customers who bought a bag on a later day, anywhere, or whose later chat converted.",
    "Value Recovered": "What recovered customers spent on the day they first came back.",
    "After a Follow-up": "Recoveries where a follow-up was recorded before they bought.",
    "Days to Recover": "Median days from first lost to bought.",
    "Ready to Recycle": "Due a follow-up now: past the fresh window, no call-back booked, under the follow-up limit.",
    "Scheduled": "A call-back date still to come.",
    "Fresh": "Touched recently — still with the team that took it.",
    "Nurture Only": "Followed up the maximum number of times without a sale — offers and broadcasts only.",
    "Never Followed Up": "Past the fresh window with no follow-up recorded — the gap to close.",
    "On the List": "Customers on today's call list after the filters.",
    "Stock Is Back": "On the list and asked for a bag that is in stock now.",
    "Said They'd Buy": "On the list and said they'd buy later or visit the shop.",
    # ---- hybrid conversion
    "Online Customers": "Customers (by phone) who messaged on WhatsApp or a social DM in the range.",
    "Walked In & Bought": "Online customers who then bought a bag at a shop till in person (deliveries don't count).",
    "Walk-in Leads": "Customers captured as walk-in leads at a shop in the range.",
    "Bought Online": "Walk-in leads who then bought on the website, Jumia or as a delivery.",
    "Value": "What these customers spent on that purchase, in KES.",
    "Same Day": "Bought the same day as their first contact.",
    "Not Credited in App": "Bought, but the chat, DM or lead was never marked as converted in its app.",
    "Bought (Any Way)": "Customers who bought a bag any way — in a shop, online or delivered — within the chosen window of their first contact. ÷ customers = overall conversion.",
    "Bought Online Only": "Online customers who bought, but only online or as a delivery — never walked in.",
    "Bought in Shop Only": "Walk-in leads who bought, but only in a shop — never online or delivered.",
    "No Purchase": "Got in touch but bought nothing within the chosen window.",
    # ---- shop attendants
    "POS Sessions": "Till sessions opened in the range.",
    "Attendants & BAs": "Shop attendants and brand ambassadors who served at least one order.",
    "Nobody Recorded": "Sales with no shop attendant or BA on the order (mostly Jumia orders on the website till).",
    "Avg Revenue per Attendant per Day": "Sales made by shop attendants ÷ attendant-days (each attendant counted once for every day they recorded a sale). BAs and sales with nobody recorded are left out.",
    "Answered So Far": "People on the team list who have answered today's questionnaire.",
    "Average Score So Far": "Average mark on today's answers so far.",
    "Latest Answer": "When the most recent answer to today's questionnaire came in.",
    "Still to Answer": "People on the team list who haven't answered today's questionnaire yet.",
    "Response Rate": "Answers given ÷ answers due: everyone on the team list is due to answer every questionnaire.",
    "Answered Same Day": "Share of the answers sent on the day of their questionnaire.",
    "Completion Rate": "Share of the questions answered, on the answers given.",
    "Average Score": "Average of the form's own mark, on the answers given.",
    "Customers Converted": "Customers who bought, by phone number, who could be asked for feedback.",
    "Gave Feedback": "Of those, customers who filled in the feedback form after buying.",
    "Feedback Received": "Feedback forms received in the range.",
    "Feedback": "Feedback forms credited to the shop's sales ÷ sales made, against a 70% target.",
    "Sales Training": "The team's training: every questionnaire due at the score it got, a missed one at 0.",
    "WhatsApp Response": "The shop's average first reply to WhatsApp chats, against 3 minutes.",
    "Clocked In": "Attendants rostered today who have clocked in, in the Attendance app.",
    "Yet to Clock In": "Attendants rostered today with no clock-in yet.",
    "Late": "Clocked in after their shift start plus the grace minutes.",
    "BAs In Today": "Brand ambassadors clocked in today (they don't work every day).",
    "Leave / Off": "Attendants on leave, off or out of office today.",
    "Attendance": "Attendants' rostered days scored on time 1, late ½, absent 0, averaged (leave and days off don't count).",
    "On Time": "Of the days attendants came in, the share they clocked in within the shift start + 15-minute grace.",
    "Late Arrivals": "Clock-ins after the shift start + 15-minute grace (BAs included); late minutes are counted after the grace.",
    "Absences": "Rostered attendant-days with no clock-in (not leave or a day off).",
    "BA Days Worked": "Days brand ambassadors clocked in — they don't work every day, so only these count.",
}

_PATTERNS = [
    (re.compile(r"^Missed \d"), "People on the team list who didn't answer that day's questionnaire."),
]
_LEAD = re.compile(r"^[^\w(]+")   # medals and emoji in front of a label


def explain(label) -> str | None:
    text = _LEAD.sub("", str(label or "")).strip()
    if text in GLOSSARY:
        return GLOSSARY[text]
    return next((note for pattern, note in _PATTERNS if pattern.search(text)), None)


def install() -> None:
    """Give every metric tile its glossary entry as hover text, once per process."""
    if getattr(DeltaGenerator.metric, "_denri_help", False):
        return
    original = DeltaGenerator.metric

    def metric(self, label, value, *args, **kwargs):
        # help is the fifth argument; only fill it in when nobody passed one.
        if len(args) < 3 and not kwargs.get("help"):
            note = explain(label)
            if note:
                kwargs["help"] = note
        return original(self, label, value, *args, **kwargs)

    metric._denri_help = True
    DeltaGenerator.metric = metric
    # st.metric was bound to the main container when Streamlit loaded.
    main = st.metric.__self__
    st.metric = metric.__get__(main, DeltaGenerator)
