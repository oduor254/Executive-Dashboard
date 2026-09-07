"""Bag family and style-code normalization shared by the distribution views
and their Excel exports.

Reuses the exact master product list and color-stripping rules already
established in lib/queries.py (PRODUCT_SALES_BY_SHOP's master_order_raw,
CUSTOMER_SALES's color_list) rather than a second, independently-maintained
copy — a product name resolves to the same family here as it does on the
Product Sales masterfile check.
"""
from __future__ import annotations

import re

import pandas as pd

UNMAPPED = "UNMAPPED"

# Longest-match-first, exactly as CUSTOMER_SALES's color_list orders its own
# lookup (ORDER BY LENGTH(color) DESC) — a multi-word color like "Croc Brown"
# has to be tried before the bare "Brown" that is also its own list entry, or
# "Brown" would strip first and leave "Croc" dangling off the family name.
_COLOR_SUFFIXES = sorted([
    "Black TT", "Grey TT", "Beige TT", "Green TT",
    "Wooven Black", "Wooven Maroon", "Wooven Mustard", "Wooven Purple",
    "Wooven Cream", "Wooven Brown", "Wooven Lilac",
    "Croc Black", "Croc Brown", "Croc Mustard", "Croc Orange", "Croc Pink",
    "Dark Brown", "Mint Green", "Yellow Brown", "Yellow Dotted", "Navy Blue",
    "Antelope Brown",
    "Red.Pattern", "Red Pattern",
    "Pattern Pink", "Pattern Blue", "Pattern Red",
    "Amapiano Black", "Amapiano Brown", "Amapiano Grey", "Amapiano Nude",
    "Ankara Black", "Ankara Brown", "Ankara Grey", "Ankara Nude",
    "Black X Red",
    "Beige/Red", "Black/Cracked", "Black/Red", "Green/Red", "Maroon/Red",
    "Black/Beige", "Black/Choco", "Black/D.Brown", "Black/Grey", "Black/Spice",
    "Red/Black", "Grey/Black", "Spice/Black", "Cracked/Black", "Chocolate/Black",
    "Black 018", "Beige 018", "Dark Brown 018", "Maroon 018",
    "Titan 1", "Titan 3", "Titan 5", "Titan 6", "Titan 11", "Titan 14", "Titan 15",
    "Goyard 5",
    "Start 20", "Start 4", "Start 8",
    "Red P", "Black B", "N.Blue", "D.Brown",
    "Manyatta Dark Brown", "Manyatta Dark Green", "Manyatta Green", "Manyatta Yellow",
    "CN Black", "CN Grey", "CN Dark Brown",
    "A3 Red", "A3 Pink",
    "A4 Red", "A4 Pink",
    "A5 Red", "A5 Pink",
    "A3", "A4", "A5",
    "Crimson",
    "Beige", "Black", "Blue", "Brown", "Chocolate", "Choco",
    "Cracked", "Green", "Grey", "Gold", "Lilac", "Maroon",
    "Mustard", "Nude", "Orange", "Pink", "Purple",
    "Red", "Spice", "White", "Yellow",
], key=len, reverse=True)

# Same catalog PRODUCT_SALES_BY_SHOP ranks the masterfile against — see
# master_order_raw there. Kept as one Python list here rather than a second
# hand-typed copy of the color-stripped family names, so the two can't drift:
# a family is "known" here exactly when one of its color variants is a real
# masterfile line.
_MASTER_PRODUCTS = [
    'Ace Croc Brown','Ace Red','Ace Beige','Ace Black TT','Ace Cracked',
    'Ace Spice','Ace Chocolate','Ace Grey','Ace Dark Brown','Ace Red.Pattern',
    'Ace Mustard','Ace Croc Pink','Ace Croc Orange','Ace Croc Mustard','Ace Blue',
    'Ace Pink','Ace Brown','Ace Lilac','Ace Mint Green','Ace Green','Ace Croc Black',
    'Adrian Black','Adrian Y.Dotted','Adrian Green','Adrian Grey','Adrian Nude','Adrian Brown',
    'Alpha Travel Black','Alpha Travel Brown','Alpha Travel Nude','Alpha Travel Grey',
    'Alpha Travel Yellow Dotted','Alpha Travel Green',
    'Amari Black/Cracked','Amari Black/Yellow','Amari Black/Beige','Amari Black/Grey',
    'Amari Black/D.Brown','Amari Black/Spice','Amari Black/Red','Amari Black/Choco',
    'Amaya Black Tt','Amaya Spice','Amaya Cracked','Amaya Grey','Amaya Beige',
    'Amaya Choco','Amaya Dark Brown','Amaya Red','Amaya Croc Black','Amaya Wooven Black',
    'Amaya Wooven Maroon','Amaya Wooven Mustard','Amaya Wooven Purple','Amaya Green',
    'Amaya Lilac','Amaya Mustard',
    'Amora Black','Amora Red','Amora Pink','Amora Blue','Amora Green','Amora Mustard',
    'Amora Maroon','Amora Purple',
    'Ana Croc Mustard','Ana Croc Orange','Ana Croc Brown','Ana Croc Pink','Ana Blue',
    'Ana Pink','Ana Mustard','Ana Brown','Ana Green','Ana Red P','Ana Black',
    'Ankara Travel Black','Ankara Travel White','Ankara Travel Grey','Ankara Travel Nude',
    'Ankara Travel Brown',
    'Antitheft Black','Antitheft Brown','Antitheft Nude','Antitheft Grey',
    'Antitheft Antelope Brown','Antitheft Green','Antitheft Cn Black',
    'Aria Pro Red','Aria Pro Beige','Aria Pro Black','Aria Pro Cracked','Aria Pro Spice',
    'Aria Pro Chocolate','Aria Pro Yellow','Aria Pro Maroon','Aria Pro Amber',
    'Aria Pro Grey','Aria Pro Dark Brown',
    'Aria Sling Red','Aria Sling Beige','Aria Sling Black','Aria Sling Cracked',
    'Aria Sling Spice','Aria Sling Chocolate','Aria Sling Yellow','Aria Sling Maroon',
    'Aria Sling Amber','Aria Sling Grey','Aria Sling Dark Brown',
    'Arlo Man Bag Red','Arlo Man Bag Beige','Arlo Man Bag Black','Arlo Man Bag Cracked',
    'Arlo Man Bag Spice','Arlo Man Bag Chocolate','Arlo Man Bag Yellow','Arlo Man Bag Maroon',
    'Arlo Man Bag Amber','Arlo Man Bag Grey','Arlo Man Bag Dark Brown',
    'Arm Band Spice','Arm Band Dark Brown','Arm Band Black','Arm Band Beige',
    'Arm Band Cracked','Arm Band Grey','Arm Band Red','Arm Band Chocolate',
    'Atlas Spice','Atlas Dark Brown','Atlas Black','Atlas Beige','Atlas Cracked',
    'Atlas Grey','Atlas Red','Atlas Yellow Brown','Atlas Chocolate',
    'Aurora Spice','Aurora Red.Pattern','Aurora Dark Brown','Aurora Black','Aurora Beige',
    'Aurora Cracked','Aurora Grey','Aurora Red','Aurora Wooven Maroon','Aurora Wooven Black',
    'Aurora Chocolate',
    'Avana Hb Spice','Avana Hb Wooven Black','Avana Hb Wooven Maroon','Avana Hb Wooven Mustard',
    'Avana Hb Wooven Purple','Avana Hb Dark Brown','Avana Hb Black','Avana Hb Beige',
    'Avana Hb Cracked','Avana Hb Grey','Avana Hb Red','Avana Hb Yellow Brown',
    'Avana Hb Amber','Avana Hb Maroon','Avana Hb Red P','Avana Hb Chocolate',
    'Baby Bag Grey','Baby Bag Black','Baby Bag Nude','Baby Bag Brown','Baby Bag Green',
    'Baby Bag Yellow Dotted',
    'Bello Spice','Bello Cracked','Bello Black','Bello Grey','Bello Red','Bello Yellow',
    'Bello Chocolate','Bello Beige',
    'Belt Bag Black','Belt Bag Red','Belt Bag Cracked','Belt Bag Spice','Belt Bag Yellow',
    'Belt Bag Nude','Belt Bag Grey','Belt Bag Chocolate','Belt Bag Dark Brown',
    'Big Man Bag Black','Big Man Bag Brown','Big Man Bag Grey','Big Man Bag Nude',
    'Big Man Bag Yellow Dotted','Big Man Bag Green',
    'Bliss Chest Black','Bliss Chest Grey',
    'Bonita Black','Bonita Cracked','Bonita Beige','Bonita Spice','Bonita Grey',
    'Bonita Red','Bonita Yellow','Bonita Choco','Bonita D.Brown',
    'Brief Case Brown','Brief Case Black','Brief Case Grey','Brief Case Nude','Brief Case Green',
    'Butterfly Sling Cracked','Butterfly Sling Spice','Butterfly Sling Grey',
    'Butterfly Sling Beige','Butterfly Sling Black','Butterfly Sling Red',
    'Butterfly Sling Chocolate','Butterfly Sling Dark Brown','Butterfly Sling Yellow Brown',
    'Cairo Bp Cracked','Cairo Bp Spice','Cairo Bp Beige','Cairo Bp Black','Cairo Bp Grey',
    'Cairo Bp Red','Cairo Bp Dark Brown','Cairo Bp Yellow Brown','Cairo Bp Chocolate',
    'Callista Cracked','Callista Spice','Callista Beige','Callista Black','Callista Grey',
    'Callista Red','Callista Dark Brown','Callista Chocolate',
    'Cathy Handbag Black','Cathy Handbag Spice','Cathy Handbag Cracked','Cathy Handbag Grey',
    'Cathy Handbag Dark Brown','Cathy Handbag Beige','Cathy Handbag Red','Cathy Handbag Chocolate',
    'Celine Sling Bag Black','Celine Sling Bag Spice','Celine Sling Bag Cracked',
    'Celine Sling Bag Grey','Celine Sling Bag Beige','Celine Sling Bag Choco',
    'Celine Sling Bag Dark Brown','Celine Sling Bag Red',
    'Cess Hb Black','Cess Hb Spice','Cess Hb Cracked','Cess Hb Grey','Cess Hb Beige',
    'Cess Hb Green','Cess Hb Choco','Cess Hb Dark Brown','Cess Hb Red',
    'Charlotte Pink','Charlotte Black','Charlotte Brown','Charlotte Green','Charlotte Mustard',
    'Charlotte Croc Mustard','Charlotte Croc Orange','Charlotte Croc Brown','Charlotte Croc Pink',
    'Charlotte Grey','Charlotte Beige','Charlotte Dark Brown','Charlotte Cracked',
    'Charlotte Red','Charlotte Spice','Charlotte Chocolate','Charlotte Blue',
    'Chase Black','Chase Brown','Chase Grey','Chase Green','Chase Nude',
    'Claire Handbag Black','Claire Handbag Spice','Claire Handbag Cracked','Claire Handbag Grey',
    'Claire Handbag Wooven Maroon','Claire Handbag Wooven Black','Claire Handbag White','Claire Handbag Beige',
    'Claire Handbag Dark Brown','Claire Handbag Red',
    'Cleo Cracked','Cleo Grey','Cleo Black','Cleo Spice','Cleo Red','Cleo Chocolate',
    'Cleo Yellow Brown','Cleo Dark Brown','Cleo Beige',
    'Code 3 Nude','Code 3 Brown','Code 3 Black','Code 3 Grey','Code 3 Antelope Brown',
    'Code 3 Green','Code 3 Blue','Code 3 Crimson',
    'Code 4 Ankara Nude','Code 4 Ankara Green','Code 4 Ankara Brown','Code 4 Ankara Grey',
    'Code 4 Ankara White','Code 4 Ankara Black',
    'Code 9 Black','Code 9 Brown','Code 9 Green','Code 9 Yellow Dotted','Code 9 Grey','Code 9 Nude',
    'College Hb Brown','College Hb Green','College Hb Black','College Hb Grey',
    'College Hb Nude','College Hb Yellow Dotted',
    'Cosmo Brown','Cosmo Green','Cosmo Black','Cosmo Grey','Cosmo Nude','Cosmo Yellow Dotted',
    'Daria Chocolate','Daria Grey','Daria Cracked','Daria Dark Brown','Daria Black',
    'Daria Spice','Daria Beige',
    'Delica Black','Delica Red.Pattern','Delica Lilac','Delica Mustard','Delica Mint Green',
    'Diaper Bag Titan 15','Diaper Bag Titan 11','Diaper Bag Titan 5','Diaper Bag Titan 6',
    'Diaper Bag Pattern Blue','Diaper Bag Pattern Red','Diaper Bag Pattern Pink',
    'Don Black','Don Brown','Don Nude','Don Grey','Don Yellow Dotted','Don Green',
    'Double Press Grey','Double Press Green','Double Press Brown','Double Press Nude',
    'Double Press Black','Double Press Yellow Dotted',
    'Elektra Black','Elektra Beige','Elektra Spice','Elektra Grey','Elektra Cracked',
    'Elektra Red','Elektra Dark Brown','Elektra Choco',
    'Ella Sling Black','Ella Sling Melon','Ella Sling Silver','Ella Sling Mint Green',
    'Ella Sling Lilac','Ella Sling Mustard','Ella Sling Dark Green','Ella Sling Navy Blue',
    'Ella Sling Brown','Ella Sling Red P','Ella Sling Pink',
    'Elyse Grey','Elyse D.Brown','Elyse Spice','Elyse Cracked','Elyse Black','Elyse Red',
    'Elyse Beige','Elyse Chocolate','Elyse Red/Black','Elyse Spice/Black','Elyse Red/Beige',
    'Elyse Black/Grey','Elyse Black/Cracked',
    'Esmeralda Black','Esmeralda Brown','Esmeralda Nude','Esmeralda Green','Esmeralda Grey',
    'Esmeralda Red','Esmeralda Blue',
    'Fabela Black','Fabela Brown','Fabela Grey','Fabela Yellow Dotted','Fabela Green','Fabela Nude',
    'Fanny Amapiano Black','Fanny Amapiano Brown','Fanny Amapiano Grey','Fanny Amapiano Cracked',
    'Fanny Amapiano Nude',
    'Fanny Pack Black','Fanny Pack Brown','Fanny Pack Grey','Fanny Pack Green',
    'Fanny Pack Cracked','Fanny Pack Nude','Fanny Pack Dark Brown','Fanny Pack Black Tt',
    'Fanny Pack Spice','Fanny Pack Yellow Dotted','Fanny Pack Grey Tt','Fanny Pack Black Mpw',
    'Fanny Pack Beige Tt',
    'Fayola Black','Fayola Grey','Fayola Nude','Fayola Green','Fayola Brown',
    'Fayola Yellow Dotted','Fayola Titan 15',
    'Feroz Grey','Feroz Red','Feroz Spice','Feroz Beige','Feroz Cracked','Feroz Black',
    'Feroz Choco','Feroz Dark Brown','Feroz Yellow Brown',
    'Foxy Melon','Foxy Mustard','Foxy Blue','Foxy Pink','Foxy Brown','Foxy Green','Foxy Black',
    'Gift Bag A3','Gift Bag A4','Gift Bag A5','Gift Bag A4 Red',
    'Gym Bag Brown','Gym Bag Green','Gym Bag Black','Gym Bag Grey','Gym Bag Nude',
    'Gym Bag Yellow Dotted',
    'Hood White','Hood N.Blue','Hood Green','Hood Maroon','Hood Grey','Hood Black','Hood Red',
    'Icon Black','Icon Spice','Icon Grey','Icon Beige','Icon Cracked','Icon Red','Icon Choco',
    'Imani Black 018','Imani Maroon 018','Imani Dark Brown 018','Imani Spice','Imani Grey',
    'Imani Beige','Imani Red','Imani Beige 018','Imani Green Tt',
    'Jabari Beige','Jabari Cracked','Jabari Maroon','Jabari Black','Jabari Dark Brown',
    'Jade Spice','Jade Dark Brown','Jade Black','Jade Beige','Jade Cracked','Jade Grey',
    'Jade Red','Jade Yellow Brown','Jade Chocolate',
    'Jamela Spice','Jamela Grey','Jamela Cracked','Jamela Black','Jamela Red',
    'Jamela Yellow Brown','Jamela Chocolate','Jamela Beige','Jamela Dark Brown',
    'Jayden Man Black','Jayden Man Brown','Jayden Man Grey','Jayden Man Nude',
    'Jayden Man Green','Jayden Man Yellow Dotted',
    'Jumbo Black','Jumbo Brown','Jumbo Green','Jumbo Grey','Jumbo Nude','Jumbo Crimson',
    'Jumbo Blue','Jumbo Yellow Dotted',
    'Kai Black','Kai Grey','Kai Brown','Kai Beige','Kai Yellow Dotted','Kai Green',
    'Kanji Spice','Kanji Black','Kanji Red','Kanji Navy','Kanji Choco','Kanji Beige',
    'Kanji Cracked','Kanji Grey','Kanji Dark Brown',
    'Kaos Grey','Kaos Spice','Kaos Cracked','Kaos Beige','Kaos Red','Kaos Black',
    'Kaos Choco','Kaos Dark Brown','Kaos Yellow Brown',
    'Karina Croc Black','Karina Red.Pattern','Karina Wooven Black','Karina Wooven Maroon',
    'Karina Grey','Karina Spice','Karina Cracked','Karina Beige','Karina Red','Karina Black',
    'Karina Choco','Karina Dark Brown','Karina Wooven Mustard','Karina Wooven Purple',
    'Karina Croc Mustard','Karina Croc Brown','Karina Croc Pink','Karina Croc Orange',
    'Kate Wooven Black','Kate Red.Pattern','Kate Maroon','Kate Wooven Mustard',
    'Kate Wooven Purple','Kate Black/Red','Kate Maroon/Masturd','Kate Green/Red',
    'Kate Brown/Red','Kate Black/Maroon','Kate Mustard/Red','Kate Yellow Brown',
    'Kate Black','Kate Spice','Kate Grey','Kate Cracked','Kate Red','Kate Beige',
    'Kate Dark Brown','Kate Chocolate',
    'Kayla Dark Brown','Kayla Cracked','Kayla Spice','Kayla Grey','Kayla Black',
    'Kayla Chocolate','Kayla Red',
    'Kaz Black','Kaz Yellow Dotted','Kaz Brown','Kaz Nude','Kaz Grey','Kaz Green',
    'Ladona Spice','Ladona Dark Brown','Ladona Black','Ladona Beige','Ladona Cracked',
    'Ladona Grey','Ladona Red','Ladona Yellow Brown','Ladona Chocolate',
    'Lamora Black','Lamora Sky Blue','Lamora Brown','Lamora Red',
    'Lanka Wooven Black','Lanka Wooven Mustard','Lanka Wooven Purple','Lanka Wooven Maroon',
    'Legacy Black','Legacy Brown','Legacy Grey','Legacy Dark Brown','Legacy Green',
    'Legacy Cracked','Legacy Beige','Legacy Red','Legacy Antelope Brown',
    'Leila Spice','Leila Red.Pattern','Leila Black','Leila Chocolate','Leila Red',
    'Leila Beige','Leila Grey','Leila Cracked','Leila Dark Brown',
    'Liam Black','Liam Brown','Liam Nude','Liam Green','Liam Grey','Liam Red',
    'Lite Black/Brown','Lite Brown/Black','Lite Grey/Black','Lite Nude/Black','Lite Green/Black',
    'Lola Yellow Brown','Lola Red.Pattern','Lola Wooven Black','Lola Wooven Maroon',
    'Lola Wooven Mustard','Lola Wooven Purple','Lola Grey','Lola Choco','Lola Cracked',
    'Lola Red','Lola Black','Lola Spice','Lola Beige','Lola Maroon','Lola Dark Brown',
    'Loop Bp Cn Black','Loop Bp Spice','Loop Bp Cracked','Loop Bp Beige','Loop Bp Maroon',
    'Loop Bp Green','Loop Bp Cn Grey','Loop Bp Red','Loop Bp Dark Brown','Loop Bp Cn Dark Brown',
    'Lotus Grey','Lotus Cracked','Lotus Spice','Lotus Beige','Lotus Black','Lotus Red',
    'Lotus Dark Brown','Lotus Choco',
    'Luca Black','Luca Nude','Luca Brown','Luca Yellow Dotted','Luca Green','Luca Grey',
    'Luna Black','Luna Green','Luna Yellow Dotted','Luna Brown','Luna Nude','Luna Grey',
    'Luna Amapiano Black','Luna Amapiano Green','Luna Amapiano Yellow Dotted',
    'Luna Amapiano Brown','Luna Amapiano Nude','Luna Amapiano Grey',
    'Lunchset Black','Lunchset Nude','Lunchset Brown','Lunchset Yellow Dotted',
    'Lunchset Green','Lunchset Grey',
    'Make Up Pouch Brown','Make Up Pouch Black','Make Up Pouch Yellow Dotted',
    'Make Up Pouch Grey','Make Up Pouch Nude','Make Up Pouch Blue','Make Up Pouch Green',
    'Man Bag Black','Man Bag Brown','Man Bag Nude','Man Bag Grey','Man Bag Green',
    'Man Bag Yellow Dotted','Man Bag Red','Man Bag Blue',
    'Mandy Hb Black','Mandy Hb Spice','Mandy Hb Cracked','Mandy Hb Grey','Mandy Hb Choco',
    'Mandy Hb Beige','Mandy Hb Yellow Brown','Mandy Hb Dark Brown','Mandy Hb Red',
    'Marley Beige','Marley Black','Marley Maroon','Marley Dark Brown',
    'Maya Mustard','Maya Red.Pattern','Maya Wooven Black','Maya Wooven Maroon',
    'Maya Wooven Mustard','Maya Wooven Purple','Maya Black','Maya Pink','Maya Mint Green',
    'Maya Brown','Maya Lilac','Maya Blue',
    'Mega Black','Mega Brown','Mega Grey','Mega Nude','Mega Green','Mega Yellow Dotted',
    'Mini Manbag Grey','Mini Manbag Black','Mini Manbag Cracked','Mini Manbag Beige',
    'Mini Manbag Red','Mini Manbag Spice','Mini Manbag Chocolate','Mini Manbag Yellow Brown',
    'Mini Manbag Dark Brown',
    'Mini Maya Wooven Mustard','Mini Maya Red.Pattern','Mini Maya Wooven Black',
    'Mini Maya Wooven Purple','Mini Maya Wooven Maroon',
    'Mini School Black','Mini School Grey','Mini School Brown','Mini School Red',
    'Mini School Green','Mini School Nude',
    'Mini Umbra Black','Mini Umbra Grey','Mini Umbra Cracked','Mini Umbra Spice',
    'Mini Umbra Manyatta Dark Brown','Mini Umbra Manyatta Dark Green','Mini Umbra Manyatta Green',
    'Mini Umbra Manyatta Yellow','Mini Umbra Beige','Mini Umbra Dark brown','Mini Umbra Red',
    'Mini Umbra Yellow Brown','Mini Umbra Chocolate',
    'Mini Zuri Grey','Mini Zuri Wooven Black','Mini Zuri Wooven Maroon','Mini Zuri Wooven Mustard',
    'Mini Zuri Wooven Purple','Mini Zuri Black','Mini Zuri Beige','Mini Zuri Red',
    'Mini Zuri Spice','Mini Zuri Cracked','Mini Zuri Maroon','Mini Zuri Amber Brown',
    'Mini Zuri Yellow Brown','Mini Zuri Chocolate','Mini Zuri Red P','Mini Zuri Dark Brown',
    'Modern Travel Grey','Modern Travel Green','Modern Travel Brown','Modern Travel Nude',
    'Modern Travel Black','Modern Travel Yellow Dotted',
    'Monah Bp Black','Monah Bp Spice','Monah Bp Cracked','Monah Bp Grey','Monah Bp Beige',
    'Monah Bp Maroon','Monah Bp Choco','Monah Bp Dark Brown','Monah Bp Red',
    'Montana Beige','Montana Black','Montana Choco','Montana Cracked','Montana Cream',
    'Montana Dark Brown','Montana Green Tt','Montana Grey','Montana Red','Montana Spice',
    'Moon Bag Spice','Moon Bag Red.Pattern','Moon Bag Wooven Black','Moon Bag Wooven Maroon',
    'Moon Bag Wooven Mustard','Moon Bag Wooven Purple','Moon Bag Grey','Moon Bag Cracked',
    'Moon Bag Black','Moon Bag Beige','Moon Bag Red','Moon Bag Yellow Brown',
    'Moon Bag Chocolate Brown','Moon Bag Maroon','Moon Bag Amber Brown','Moon Bag Dark Brown',
    'Mradi Travel Black','Mradi Travel Brown','Mradi Travel Green','Mradi Travel Yellow Dotted',
    'Mradi Travel Grey','Mradi Travel Nude',
    'Mystique Grey','Mystique Black','Mystique Cracked','Mystique Beige','Mystique Red',
    'Mystique Spice','Mystique Chocolate','Mystique Yellow Brown','Mystique Dark Brown',
    'Nala Black','Nala Blue','Nala Red','Nala Green',
    'Neo Man Black','Neo Man Grey','Neo Man Brown','Neo Man Green','Neo Man Nude',
    'Neo Man Yellow Dotted',
    'Nina Mustard','Nina Black','Nina Lilac','Nina Pink','Nina Blue','Nina Green',
    'Nina Maroon','Nina Mint Green','Nina Brown',
    'Nizana Black','Nizana Red.Pattern','Nizana Cracked','Nizana Spice','Nizana Grey',
    'Nizana Beige','Nizana Choco','Nizana Yellow Brown','Nizana Red','Nizana Dark Brown',
    'Nova Spice','Nova Grey','Nova Black','Nova Nude','Nova Cracked','Nova Chocolate',
    'Nova Yellow Brown',
    'Nyla Bp Black','Nyla Bp Brown','Nyla Bp Nude','Nyla Bp Grey','Nyla Bp Yellow Dotted',
    'Nyla Bp Green',
    'Oval Handbag Brown','Oval Handbag Wooven Black','Oval Handbag Wooven Maroon',
    'Oval Handbag Wooven Mustard','Oval Handbag Wooven Purple','Oval Handbag Grey',
    'Oval Handbag Green','Oval Handbag Nude','Oval Handbag Black','Oval Handbag Red',
    'Oval Handbag Red P','Oval Handbag Chocolate',
    'Pioneer Black','Pioneer Brown','Pioneer Grey','Pioneer Nude','Pioneer Green',
    'Pioneer Yellow Dotted',
    'Pocket Travel Black','Pocket Travel Brown','Pocket Travel Nude','Pocket Travel Yellow Dotted',
    'Pocket Travel Green','Pocket Travel Grey',
    'POH Hairistic Spice','POH Hairistic Grey','POH Hairistic Brown','POH Hairistic Cracked',
    'POH Hairistic Red','POH Hairistic Choco','POH Hairistic Black',
    'Prime Black','Prime Brown','Prime Nude','Prime Grey','Prime Yellow Dotted',
    'Prime Green','Prime Red',
    'Reesto Chest Grey','Reesto Chest Spice','Reesto Chest Cracked','Reesto Chest Beige',
    'Reesto Chest Red','Reesto Chest Black','Reesto Chest Choco','Reesto Chest Dark Brown',
    'Reesto Chest Yellow Brown',
    'Remi Spice','Remi Dark Brown','Remi Black','Remi Beige','Remi Cracked','Remi Grey',
    'Remi Red','Remi Yellow Brown','Remi Chocolate',
    'Reo Travel Black','Reo Travel Brown','Reo Travel Nude','Reo Travel Grey',
    'Reo Travel Yellow Dotted','Reo Travel Green',
    'Roza Cracked','Roza Spice','Roza Grey','Roza Black','Roza Red','Roza Yellow Brown',
    'Roza Chocolate','Roza Dark Brown','Roza Maroon','Roza Beige',
    'Safiri Bp Black','Safiri Bp Brown','Safiri Bp Nude','Safiri Bp Grey','Safiri Bp Green',
    'Safiri Travel Brown','Safiri Travel Black','Safiri Travel Grey','Safiri Travel Nude',
    'Safiri Travel Yellow Dotted','Safiri Travel Crimson','Safiri Travel Green',
    'Santana Mint Green','Santana Red.Pattern','Santana Black','Santana Mustard','Santana Lilac',
    'Sarai Nude','Sarai Yellow Doted','Sarai Black','Sarai Green','Sarai Grey','Sarai Brown',
    'Satchel Black','Satchel Grey','Satchel Spice','Satchel Cracked','Satchel Red',
    'Satchel Beige','Satchel Wooven Black','Satchel Chocolate','Satchel Yellow Brown',
    'Satis Black','Satis Cracked','Satis Spice','Satis Grey','Satis Red','Satis Beige',
    'Satis Yellow Brown','Satis Amber','Satis D.Brown','Satis Chocolate',
    'Savannah Sling Black','Savannah Sling Caramel','Savannah Sling Mustard',
    'Savannah Sling Maroon','Savannah Sling Cream',
    'Scarlet Black','Scarlet Croc.Pink','Scarlet Croc.Orange','Scarlet Croc.Mustard',
    'Scarlet Croc.Brown',
    'School Bag Black','School Bag Brown','School Bag Beige','School Bag Grey',
    'School Bag Green','School Bag Blue',
    'Scooby Black','Scooby Dark Brown','Scooby Spice','Scooby Grey','Scooby Red',
    'Scooby Cracked','Scooby Choco','Scooby Beige',
    'Shugli Backpack Brown','Shugli Backpack Black','Shugli Backpack Grey',
    'Shugli Backpack Yellow Dotted','Shugli Backpack Green','Shugli Backpack Nude',
    'Sierra Handbag Wooven Black','Sierra Handbag Wooven Cream','Sierra Handbag Wooven Maroon',
    'Sierra Handbag Wooven Brown',
    'Skye Hb Wooven Black','Skye HB Wooven Lilac','Skye Hb Wooven Maroon','Skye Hb Wooven Mustard',
    'Sleeve 1 Caramel','Sleeve 1 Black','Sleeve 1 Brown','Sleeve 1 Green',
    'Sleeve 2 Caramel','Sleeve 2 Black','Sleeve 2 Brown','Sleeve 2 Green',
    'Spark Black','Spark Brown','Spark Grey','Spark Nude','Spark Green','Spark Yellow Dotted',
    'Splash Backpack Black','SPlash Backpack Green','Splash Backpack Brown',
    'Splash Backpack Beige','Splash Backpack Grey',
    'Taji Black','Taji Maroon 018','Taji Dark Brown','Taji Beige','Taji Brown','Taji Green',
    'Taji Red','Taji Blue','Taji Grey',
    'Titan Travel Titan 1','Titan Travel Titan 15','Titan Travel Titan 5','Titan Travel Titan 14',
    'Titan Travel Titan 11','Titan Travel Titan 3','Titan Travel Titan 6',
    'Standard Travel Grey','Standard Travel Yellow Dotted','Standard Travel Nude',
    'Standard Travel Brown','Standard Travel Black','Standard Travel Red',
    'Standard Travel Blue','Standard Travel Green',
    'Travolta Black','Travolta Dark Brown','Travolta Spice','Travolta Grey','Travolta Red',
    'Travolta Cracked','Travolta Choco','Travolta Beige',
    'Trecento Spice','Trecento Grey','Trecento Cracked','Trecento Black','Trecento Red',
    'Trecento Wooven Maroon','Trecento Chocolate','Trecento Dark Brown','Trecento Red P',
    'Trecento Beige',
    'Trio Mio Black','Trio Mio Grey','Trio Mio Nude','Trio Mio Green','Trio Mio Brown',
    'Twain Travel Grey','Twain Travel Beige','Twain Travel Red','Twain Travel Spice',
    'Twain Travel Cracked','Twain Travel Yellow Brown','Twain Travel Chocolate',
    'Twain Travel Dark Brown',
    'Tyler Black','Tyler Yellow Dotted','Tyler Brown','Tyler Grey','Tyler Nude','Tyler Green',
    'Umbra Cracked','Umbra Spice','Umbra Grey','Umbra Beige','Umbra Green','Umbra Red',
    'Umbra Black','Umbra Dark Brown','Umbra Chocolate',
    'Val Croc Orange','Val Croc Pink','Val Croc Brown','Val Black','Val Red','Val Croc Mustard',
    'Vanity Spice','Vanity Dark Brown','Vanity Black','Vanity Beige','Vanity Cracked',
    'Vanity Grey','Vanity Red','Vanity Yellow Brown','Vanity Amber','Vanity Maroon',
    'Vanity Chocolate',
    'Voyage Black','Voyage Brown','Voyage Green','Voyage Grey','Voyage Nude','Voyage Red',
    'Voyage Blue','Voyage Yellow Dotted',
    'Wander Luxe Pattern Pink','Wander Luxe Pattern Blue','Wander Luxe Pattern Red',
    'Washbag Black','Washbag Brown','Washbag Nude','Washbag Grey','Washbag Yellow Dotted',
    'Washbag Green',
    'Yara Melon','Yara Mustard','Yara Blue','Yara Pink','Yara Brown','Yara Green','Yara Black',
    'Zane Man Black','Zane Man Cracked','Zane Man Beige','Zane Man Spice','Zane Man Grey',
    'Zane Man Chocolate','Zane Man Red','Zane Man Green','Zane Man Dark Brown',
    'Zelus Black','Zelus Cracked','Zelus Beige','Zelus Spice','Zelus Grey','Zelus Chocolate',
    'Zelus Dark Brown','Zelus Yellow Brown',
    'Zeno Grey/Black','Zeno Spice/Black','Zeno Black/Grey','Zeno Cracked/Black',
    'Zeno Yellow Brown','Zeno Chocolate/Black','Zeno Black/Red','Zeno Black/Cracked',
    'Ziara Man Bag Brown','Ziara Man Bag Black','Ziara Man Bag Nude','Ziara Man Bag Green',
    'Ziara Man Bag Yellow Dotted','Ziara Man Bag Grey',
    'Zing Sling Black','Zing Sling Spice','Zing Sling Cracked','Zing Sling Grey',
    'Zing Sling Yellow Brown','Zing Sling Chocolate','Zing Sling Red','Zing Sling Beige',
    'Zing Sling Dark Brown',
    'Zipped Lunchset Grey','Zipped Lunchset Brown','Zipped Lunchset Beige',
    'Zipped Lunchset Black','Zipped Lunchset Yellow Dotted','Zipped Lunchset Green',
    'Zoezi Brown','Zoezi Green','Zoezi Nude','Zoezi Black','Zoezi Grey','Zoezi Yellow Dotted',
    'Zula Cn Black','Zula Cn Grey','Zula Antelope Brown','Zula Nude','Zula Green','Zula Red',
    'Zula Black','Zula Yellow Dotted',
    'Zuri Red','Zuri Red.Pattern','Zuri Beige','Zuri Black','Zuri Cracked','Zuri Spice',
    'Zuri Chocolate','Zuri Yellow','Zuri Maroon','Zuri Amber','Zuri Grey','Zuri Dark Brown',
]


def _strip_color(name: str) -> str:
    """Longest color suffix removed, case-insensitively — mirrors
    product_color_split's `pt.name LIKE '% ' || cl.color OR pt.name = cl.color`
    with colors tried longest-first."""
    name = name.strip()
    lowered = name.lower()
    for color in _COLOR_SUFFIXES:
        color_lower = color.lower()
        if lowered == color_lower:
            return ""
        suffix = " " + color_lower
        if lowered.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def _build_family_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for product in _MASTER_PRODUCTS:
        family = _strip_color(product)
        key = family.upper()
        if key and key not in index:
            index[key] = family
    return index


_FAMILY_INDEX = _build_family_index()


def family_of(name) -> str:
    """The bag family a product belongs to ("Man Bag Black" -> "Man Bag"), or
    UNMAPPED if no color-stripped form of it is a masterfile family — the same
    check that flags a product as off-catalog in Product Sales, reused here so
    "unrecognized" means the same thing on both pages."""
    if not name:
        return UNMAPPED
    key = _strip_color(str(name)).upper()
    return _FAMILY_INDEX.get(key, UNMAPPED)


_STYLE_CODE_RE = re.compile(r"\s+018$", re.IGNORECASE)


def base_name(name) -> str:
    """Product name with a trailing " 018" style-code stripped. Odoo carries
    some colors as two separate SKUs (plain and "... 018") for what is, on the
    shop floor, the same bag — this is the name they share once that's gone."""
    return _STYLE_CODE_RE.sub("", str(name)).strip()


def merge_style_codes(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Fold "X 018" rows into their plain "X" counterpart.

    Numeric columns sum across the folded rows; every other column keeps
    whichever row's value arrived first, since a folded pair's other columns
    (Family, sort_order, ...) already agree by construction.
    """
    if df.empty:
        return df

    original_columns = list(df.columns)
    working = df.copy()
    working["_base"] = working[column].astype(str).map(base_name)

    numeric_cols = [c for c in working.select_dtypes(include="number").columns
                     if c != "_base"]
    other_cols = [c for c in original_columns if c != column and c not in numeric_cols]

    agg = {c: "sum" for c in numeric_cols}
    agg.update({c: "first" for c in other_cols})

    merged = working.groupby("_base", as_index=False, sort=False).agg(agg)
    merged = merged.rename(columns={"_base": column})
    return merged[original_columns]
