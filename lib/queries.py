"""SQL for each dashboard domain.

Each query is parameterized (never string-interpolated) and run through
lib.db.run_query(sql, params) so values are always bound, not concatenated.
"""

SALES_PERFORMANCE_BY_BRANCH = """
WITH date_range AS (
    SELECT
        CAST(:start_date AS DATE) AS start_date,
        CAST(:end_date AS DATE) AS end_date
),

branch_totals AS (
    SELECT
        CASE
            WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%'
                THEN 'Sinza'
            ELSE INITCAP(
                    TRIM(REGEXP_REPLACE(
                        COALESCE(sw.name, sl.complete_name, 'N/A'),
                        '\\s*Shop\\s*', '', 'gi'
                    ))
                )
        END                                                         AS branch,

        ROUND(SUM(
            CASE
                WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%'
                    THEN pol.price_subtotal_incl / 25
                WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Uganda%'
                    THEN pol.price_subtotal_incl / 29
                ELSE pol.price_subtotal_incl
            END
        ), 0)                                                       AS revenue,

        SUM(pol.qty)                                                AS qty,

        COUNT(DISTINCT CASE
            WHEN po.customer_type = 'walkin' THEN po.id
        END)                                                        AS walk_in_orders,

        COUNT(DISTINCT CASE
            WHEN po.customer_type = 'online' THEN po.id
        END)                                                        AS online_orders,

        COUNT(DISTINCT CASE
            WHEN po.customer_type = 'activation' THEN po.id
        END)                                                        AS activation_orders,

        COUNT(DISTINCT po.id)                                       AS orders

    FROM pos_order po

    LEFT JOIN pos_order_line       pol   ON pol.order_id = po.id
    LEFT JOIN product_product      pp    ON pp.id    = pol.product_id
    LEFT JOIN product_template     pt    ON pt.id    = pp.product_tmpl_id
    LEFT JOIN product_category     pc    ON pc.id    = pt.categ_id
    LEFT JOIN pos_session          ps    ON ps.id    = po.session_id
    LEFT JOIN pos_config           pconf ON pconf.id = ps.config_id
    LEFT JOIN stock_picking_type   spt   ON spt.id   = pconf.picking_type_id
    LEFT JOIN stock_warehouse      sw    ON sw.id    = spt.warehouse_id
    LEFT JOIN stock_location       sl    ON sl.id    = spt.default_location_src_id,
    date_range dr

    WHERE
        po.state IN ('done', 'paid')
        AND pt.name NOT ILIKE '%Delivery Fee%'
        AND pt.name NOT ILIKE '%Gift Bag%'
        AND pc.name NOT ILIKE '%Pos%'
        AND pol.qty > 0
        AND pt.name NOT ILIKE '%KES discount%'
        AND po.date_order::DATE BETWEEN dr.start_date AND dr.end_date

    GROUP BY
        CASE
            WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%'
                THEN 'Sinza'
            ELSE INITCAP(
                    TRIM(REGEXP_REPLACE(
                        COALESCE(sw.name, sl.complete_name, 'N/A'),
                        '\\s*Shop\\s*', '', 'gi'
                    ))
                )
        END
),

period_target AS (
    SELECT
        CASE
            WHEN (SELECT end_date FROM date_range) - (SELECT start_date FROM date_range) <= 1 THEN 'day'
            WHEN (SELECT end_date FROM date_range) - (SELECT start_date FROM date_range) <= 7 THEN 'week'
            ELSE 'month'
        END AS selected_period
),

branch_mapping AS (
    SELECT 'Sinza' AS branch_name, 'DAR-ES-ALAM' AS target_branch
    UNION ALL SELECT 'Website', 'WEBSITE SALES'
    UNION ALL SELECT 'Ktda', 'KTDA Shop'
    UNION ALL SELECT 'Hilton', 'HILTON'
    UNION ALL SELECT 'Busia', 'BUSIA'
    UNION ALL SELECT 'Corporate', 'CORPORATE'
    UNION ALL SELECT 'Nairobi', 'NAIROBI'
    UNION ALL SELECT 'Kisumu', 'KISUMU'
    UNION ALL SELECT 'Thika', 'THIKA'
    UNION ALL SELECT 'Hazina', 'HAZINA'
    UNION ALL SELECT 'Mombasa', 'MOMBASA'
    UNION ALL SELECT 'Uganda', 'UGANDA'
    UNION ALL SELECT 'Starmall', 'STARMALL'
    UNION ALL SELECT 'Nanyuki', 'NANYUKI'
    UNION ALL SELECT 'Nakuru', 'NAKURU'
    UNION ALL SELECT 'Eldoret', 'ELDORET'
    UNION ALL SELECT 'Rongai', 'RONGAI'
    UNION ALL SELECT 'Kisii', 'KISII'
    UNION ALL SELECT 'Kakamega', 'KAKAMEGA'
    UNION ALL SELECT 'Kitengela', 'KITENGELA'
    UNION ALL SELECT 'Meru', 'MERU'
),

results AS (
    SELECT
        bt.branch                                                       AS "Branch",
        bt.revenue                                                      AS "Revenue",
        bt.qty                                                          AS "Qty",
        bt.walk_in_orders                                               AS "Walk-in Orders",
        bt.online_orders                                                AS "Online Orders",
        bt.activation_orders                                            AS "Activation Orders",
        bt.orders                                                       AS "Orders",
        COALESCE(spt.target_amount, 0)                                  AS "Target",
        ROUND(
            CASE
                WHEN COALESCE(spt.target_amount, 0) = 0 THEN 0
                ELSE (bt.revenue::NUMERIC / spt.target_amount * 100)
            END,
            2
        )                                                               AS "% Achieved",
        0                                                               AS sort_order

    FROM branch_totals bt
    LEFT JOIN branch_mapping bm ON LOWER(bt.branch) = LOWER(bm.branch_name)
    LEFT JOIN sales_pos_target spt ON (
        spt.name ILIKE bm.target_branch || '%'
        AND spt.period = (SELECT selected_period FROM period_target)
        AND (SELECT end_date FROM date_range) BETWEEN spt.start_date AND spt.end_date
    )

    UNION ALL

    SELECT
        'GRAND TOTAL'                                                   AS "Branch",
        SUM(bt.revenue)                                                 AS "Revenue",
        SUM(bt.qty)                                                     AS "Qty",
        SUM(bt.walk_in_orders)                                          AS "Walk-in Orders",
        SUM(bt.online_orders)                                           AS "Online Orders",
        SUM(bt.activation_orders)                                       AS "Activation Orders",
        SUM(bt.orders)                                                  AS "Orders",
        (
            SELECT COALESCE(SUM(target_amount), 0)
            FROM sales_pos_target
            WHERE period = (SELECT selected_period FROM period_target)
            AND (SELECT end_date FROM date_range) BETWEEN start_date AND end_date
            AND name NOT ILIKE '%FLASH SALE%'
        )                                                               AS "Target",
        ROUND(
            (SUM(bt.revenue)::NUMERIC /
            (SELECT COALESCE(SUM(target_amount), 1) FROM sales_pos_target
             WHERE period = (SELECT selected_period FROM period_target)
             AND (SELECT end_date FROM date_range) BETWEEN start_date AND end_date
             AND name NOT ILIKE '%FLASH SALE%') * 100),
            2
        )                                                               AS "% Achieved",
        1                                                               AS sort_order

    FROM branch_totals bt
)

SELECT
    "Branch",
    "Revenue",
    "Qty",
    "Walk-in Orders",
    "Online Orders",
    "Activation Orders",
    "Orders",
    "Target",
    "% Achieved"
FROM results
ORDER BY sort_order, "% Achieved" DESC;
"""

# One row per SHOP + PRODUCT with quantity sold, over the given date range.
# Masterfile products (the official catalog) are ranked first by qty sold,
# then non-masterfile products (off-catalog/unlisted) below them, each block
# sorted highest to lowest, with a TOTAL row closing out each block.
PRODUCT_SALES_BY_SHOP = """
WITH date_range AS (
  SELECT
    CAST(:start_date AS DATE) AS start_date,
    CAST(:end_date AS DATE) AS end_date
),

master_order_raw AS (
  SELECT name, ord
  FROM UNNEST(ARRAY[
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
    'Zuri Chocolate','Zuri Yellow','Zuri Maroon','Zuri Amber','Zuri Grey','Zuri Dark Brown'
  ]) WITH ORDINALITY AS t(name, ord)
),

-- Dedupe repeated masterfile names (keep first position)
master_order AS (
  SELECT DISTINCT ON (UPPER(TRIM(name)))
    UPPER(TRIM(name)) AS product_key,
    ord               AS sort_order
  from master_order_raw
  ORDER BY UPPER(TRIM(name)), ord
),

shop_sales AS (
  SELECT
    CASE
      WHEN lower(pc."name") IN ('website sales','website','jumia') OR p.session_id IS NULL THEN 'WEBSITE'
      WHEN lower(pc."name") IN ('sinza','dar-es-alam')             THEN 'SINZA'
      WHEN lower(pc."name") IN ('ktda','ktda shop')                THEN 'KTDA'
      ELSE UPPER(pc."name")
    END AS shop,
    COALESCE(pt."name", '<<unknown>>') AS product_name,
    SUM(pl.qty) AS qty_sold
  FROM pos_order p
  JOIN pos_order_line pl ON pl.order_id = p.id
  LEFT JOIN pos_session ps ON p.session_id = ps.id
  LEFT JOIN pos_config pc ON ps.config_id = pc.id
  LEFT JOIN product_product pp ON pl.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  LEFT JOIN product_category pcat ON pcat.id = pt.categ_id
  CROSS JOIN date_range dr
  WHERE p.date_order::date BETWEEN dr.start_date AND dr.end_date
    AND p.state IN ('done', 'paid')
    AND COALESCE(pt."name", '') NOT LIKE '%+%'
    AND COALESCE(pt."name", '') NOT ILIKE '%Delivery Fee%'
    AND COALESCE(pt."name", '') NOT ILIKE '%Gift Bag%'
    AND COALESCE(pt."name", '') NOT ILIKE '%KES discount%'
    AND COALESCE(pcat."name", '') NOT ILIKE '%Pos%'
    AND pl.qty > 0
  GROUP BY 1, 2
  HAVING SUM(pl.qty) <> 0
),

tagged AS (
  SELECT
    ss.shop,
    ss.product_name,
    ss.qty_sold,
    CASE WHEN mo.product_key IS NOT NULL THEN 0 ELSE 1 END AS section,
    0 AS row_type
  FROM shop_sales ss
  LEFT JOIN master_order mo
    ON mo.product_key = UPPER(TRIM(ss.product_name))
),

section_totals AS (
  SELECT
    '' AS shop,
    CASE section
      WHEN 0 THEN 'MASTERFILE TOTAL'
      ELSE        'NON-MASTERFILE TOTAL'
    END AS product_name,
    SUM(qty_sold) AS qty_sold,
    section,
    1 AS row_type
  FROM tagged
  GROUP BY section
)

SELECT
  shop         AS "SHOP",
  product_name AS "PRODUCT",
  qty_sold     AS "QTY SOLD"
FROM (
  SELECT * FROM tagged
  UNION ALL
  SELECT * FROM section_totals
) combined
ORDER BY
  section,
  row_type,
  qty_sold DESC,
  product_name,
  shop;
"""

# One row per sold order line: cleaned customer name/gender/phone, parsed
# product + color, category, branch, and KES-normalized price/total.
CUSTOMER_SALES = """
WITH color_list(color) AS (
    VALUES
        -- Multi-word colors (longest match wins)
        ('Black TT'),('Grey TT'),('Beige TT'),('Green TT'),
        ('Wooven Black'),('Wooven Maroon'),('Wooven Mustard'),('Wooven Purple'),
        ('Wooven Cream'),('Wooven Brown'),('Wooven Lilac'),
        ('Croc Black'),('Croc Brown'),('Croc Mustard'),('Croc Orange'),('Croc Pink'),
        ('Dark Brown'),('Mint Green'),('Yellow Brown'),('Yellow Dotted'),('Navy Blue'),
        ('Antelope Brown'),
        ('Red.Pattern'),('Red Pattern'),
        ('Pattern Pink'),('Pattern Blue'),('Pattern Red'),
        ('Amapiano Black'),('Amapiano Brown'),('Amapiano Grey'),('Amapiano Nude'),
        ('Ankara Black'),('Ankara Brown'),('Ankara Grey'),('Ankara Nude'),
        ('Black X Red'),
        ('Beige/Red'),('Black/Cracked'),('Black/Red'),('Green/Red'),('Maroon/Red'),
        ('Black/Beige'),('Black/Choco'),('Black/D.Brown'),('Black/Grey'),('Black/Spice'),
        ('Red/Black'),('Grey/Black'),('Spice/Black'),('Cracked/Black'),('Chocolate/Black'),
        ('Black 018'),('Beige 018'),('Dark Brown 018'),('Maroon 018'),
        ('Titan 1'),('Titan 3'),('Titan 5'),('Titan 6'),('Titan 11'),('Titan 14'),('Titan 15'),
        ('Goyard 5'),
        ('Start 20'),('Start 4'),('Start 8'),
        ('Red P'),('Black B'),('N.Blue'),('D.Brown'),
        ('Manyatta Dark Brown'),('Manyatta Dark Green'),('Manyatta Green'),('Manyatta Yellow'),
        ('CN Black'),('CN Grey'),('CN Dark Brown'),
        ('A3 Red'),('A3 Pink'),
        ('A4 Red'),('A4 Pink'),
        ('A5 Red'),('A5 Pink'),
        ('A3'),('A4'),('A5'),
        ('Crimson'),
        ('Beige'),('Black'),('Blue'),('Brown'),('Chocolate'),('Choco'),
        ('Cracked'),('Green'),('green'),('GREEN'),('Grey'),('Gold'),('Lilac'),('Maroon'),
        ('Mustard'),('Nude'),('Orange'),('Pink'),('Purple'),
        ('Red'),('Spice'),('White'),('Yellow')
),

product_color_split AS (
    SELECT
        pt.id AS product_tmpl_id,
        pt.name AS full_name,
        (
            SELECT cl.color
            FROM color_list cl
            WHERE pt.name LIKE '% ' || cl.color
               OR pt.name = cl.color
            ORDER BY LENGTH(cl.color) DESC
            LIMIT 1
        ) AS matched_color
    FROM product_template pt
),

customer_name_split AS (
    SELECT
        rp.id,
        INITCAP(
            TRIM(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            REGEXP_REPLACE(
                                REGEXP_REPLACE(
                                    rp.name,
                                    '\\([^)]*\\)',
                                    '', 'g'
                                ),
                                '(?i)\\s*(prepayment fulfilled|prepayment|sasapay|sasa pay|fullfilled|fulfilled|prepay|coop|I&M|ncba|cash|pdq)\\s*',
                                ' ', 'g'
                            ),
                            '[",;:'']',
                            '', 'g'
                        ),
                        '\\s+[A-Z]\\s+',
                        ' ', 'g'
                    ),
                    '\\s{2,}',
                    ' ', 'g'
                )
            )
        ) AS full_name,
        INITCAP(
            TRIM(SPLIT_PART(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            REGEXP_REPLACE(
                                REGEXP_REPLACE(
                                    rp.name,
                                    '\\([^)]*\\)',
                                    '', 'g'
                                ),
                                '(?i)\\s*(prepayment fulfilled|prepayment|sasapay|sasa pay|fullfilled|fulfilled|prepay|coop|I&M|ncba|cash|pdq)\\s*',
                                ' ', 'g'
                            ),
                            '[",;:'']',
                            '', 'g'
                        ),
                        '\\s+[A-Z]\\s+',
                        ' ', 'g'
                    ),
                    '\\s{2,}',
                    ' ', 'g'
                ),
                ' ', 1
            ))
        ) AS first_name
    FROM res_partner rp
)

SELECT
    po.date_order::DATE                                             AS "Date",

    -- First Name (handle empty cases with fallback to Name)
    CASE
        WHEN TRIM(cns.first_name) = '' OR cns.first_name IS NULL
            THEN SPLIT_PART(cns.full_name, ' ', 1)
        ELSE cns.first_name
    END                                                             AS "First Name",

    -- Name (full customer name)
    CASE
        WHEN TRIM(cns.full_name) = '' OR cns.full_name IS NULL
            THEN 'N/A'
        ELSE cns.full_name
    END                                                             AS "Name",

    -- Gender (derived from first name lookup)
    COALESCE(
        (SELECT gn.gender
         FROM (VALUES
            ('Faith','Female'),('Mercy','Female'),('Mary','Female'),('Esther','Female'),
            ('Caroline','Female'),('Grace','Female'),('Ann','Female'),('Sharon','Female'),
            ('Elizabeth','Female'),('Jane','Female'),('Lucy','Female'),('Irene','Female'),
            ('Ruth','Female'),('Christine','Female'),('Maureen','Female'),('Lilian','Female'),
            ('Cynthia','Female'),('Susan','Female'),('Margaret','Female'),('Catherine','Female'),
            ('Rose','Female'),('Joyce','Female'),('Agnes','Female'),('Lydia','Female'),
            ('Eunice','Female'),('Beatrice','Female'),('Winnie','Female'),('Pauline','Female'),
            ('Janet','Female'),('Edith','Female'),('Doris','Female'),('Alice','Female'),
            ('Purity','Female'),('Tabitha','Female'),('Naomi','Female'),('Priscilla','Female'),
            ('Vivian','Female'),('Gladys','Female'),('Judith','Female'),('Dorothy','Female'),
            ('Peninah','Female'),('Immaculate','Female'),('Jacqueline','Female'),
            ('Josephine','Female'),('Bernadette','Female'),('Anastasia','Female'),
            ('Veronica','Female'),('Perpetua','Female'),('Consolata','Female'),
            ('Magdalene','Female'),('Philomena','Female'),
            ('Wanjiru','Female'),('Wanjiku','Female'),('Wairimu','Female'),('Wangari','Female'),
            ('Njeri','Female'),('Nyambura','Female'),('Mumbi','Female'),('Wambui','Female'),
            ('Gathoni','Female'),('Wangui','Female'),('Waithira','Female'),
            ('Akinyi','Female'),('Awino','Female'),('Atieno','Female'),('Adhiambo','Female'),
            ('Anyango','Female'),('Akello','Female'),('Auma','Female'),('Awuor','Female'),
            ('Nafula','Female'),('Nasimiyu','Female'),('Naliaka','Female'),('Nekesa','Female'),
            ('Nanjala','Female'),('Zawadi','Female'),('Rehema','Female'),('Fatuma','Female'),
            ('Amina','Female'),('Zuhura','Female'),('Halima','Female'),('Mwanaidi','Female'),
            ('Saumu','Female'),('Rukia','Female'),('Mariamu','Female'),('Hadija','Female'),
            ('Salma','Female'),('Zainab','Female'),('Khadija','Female'),('Asha','Female'),
            ('Maryam','Female'),('Aisha','Female'),('Fatima','Female'),('Hawa','Female'),
            ('Nancy','Female'),('Brenda','Female'),('Diana','Female'),('Stella','Female'),
            ('Sandra','Female'),('Angela','Female'),('Sylvia','Female'),('Monica','Female'),
            ('Rosemary','Female'),('Violet','Female'),('Claire','Female'),
            ('Rachel','Female'),('Rebecca','Female'),('Deborah','Female'),('Miriam','Female'),
            ('Hannah','Female'),('Sarah','Female'),('Leah','Female'),
            ('Charity','Female'),('Hope','Female'),('Patience','Female'),('Prudence','Female'),
            ('Happiness','Female'),('Blessing','Female'),('Precious','Female'),('Gift','Female'),
            ('Millicent','Female'),('Mildred','Female'),('Linet','Female'),('Linda','Female'),
            ('Lynette','Female'),('Lorna','Female'),('Sheila','Female'),('Sophia','Female'),
            ('Samantha','Female'),('Stacy','Female'),('Stephanie','Female'),('Suzan','Female'),
            ('Tina','Female'),('Tracy','Female'),('Valerie','Female'),('Yvonne','Female'),
            ('Ivy','Female'),('Isabella','Female'),('Hellen','Female'),('Helen','Female'),
            ('Harriet','Female'),('Florah','Female'),('Florence','Female'),('Fiona','Female'),
            ('Eva','Female'),('Evelyn','Female'),('Edna','Female'),('Eleanor','Female'),
            ('Dorcas','Female'),('Doreen','Female'),('Damaris','Female'),('Daisy','Female'),
            ('Cecilia','Female'),('Carolyne','Female'),('Brigid','Female'),('Betty','Female'),
            ('Barbara','Female'),('Audrey','Female'),('Annette','Female'),('Anita','Female'),
            ('Amanda','Female'),('Abigail','Female'),('Maurine','Female'),('Peris','Female'),
            ('Risper','Female'),('Ziporah','Female'),('Zipporah','Female'),
            ('Teresia','Female'),('Teresa','Female'),('Triza','Female'),
            ('Keziah','Female'),('Serah','Female'),('Selina','Female'),('Sabina','Female'),
            ('Roselyn','Female'),('Phyllis','Female'),('Phoebe','Female'),('Olive','Female'),
            ('Olivia','Female'),('Nelly','Female'),('Neema','Female'),
            ('Nkirote','Female'),('Nkatha','Female'),('Moraa','Female'),('Kemunto','Female'),
            ('Kerubo','Female'),('Kwamboka','Female'),('Gesare','Female'),('Nyaboke','Female'),
            ('Akoth','Female'),('Juliet','Female'),('Julia','Female'),('June','Female'),
            ('Jemimah','Female'),('Jedidah','Female'),('Imelda','Female'),
            ('Scholastica','Female'),('Gentrix','Female'),('Gertrude','Female'),
            ('Gloria','Female'),('Felicity','Female'),('Celestine','Female'),
            ('Connie','Female'),('Cordelia','Female'),('Bahati','Female'),
            ('Penelope','Female'),('Nadia','Female'),('Layla','Female'),('Yasmin','Female'),
            ('Latifa','Female'),('Zoe','Female'),('Wendy','Female'),('Shirley','Female'),
            ('Lynet','Female'),('Lucia','Female'),('Lisa','Female'),('Laura','Female'),
            ('Roseline','Female'),('Nella','Female'),('Nellie','Female'),
            ('Brian','Male'),('John','Male'),('Joseph','Male'),('Peter','Male'),
            ('James','Male'),('David','Male'),('Dennis','Male'),('George','Male'),
            ('Michael','Male'),('Paul','Male'),('Patrick','Male'),('Daniel','Male'),
            ('Robert','Male'),('Richard','Male'),('Francis','Male'),('Charles','Male'),
            ('Stephen','Male'),('Steven','Male'),('Philip','Male'),('Thomas','Male'),
            ('William','Male'),('Henry','Male'),('Edward','Male'),('Andrew','Male'),
            ('Anthony','Male'),('Mark','Male'),('Matthew','Male'),('Luke','Male'),
            ('Simon','Male'),('Samuel','Male'),('Nathan','Male'),('Isaac','Male'),
            ('Joshua','Male'),('Emmanuel','Male'),('Benjamin','Male'),('Jonathan','Male'),
            ('Timothy','Male'),('Kevin','Male'),('Kenneth','Male'),('Leonard','Male'),
            ('Lawrence','Male'),('Martin','Male'),('Moses','Male'),('Nicholas','Male'),
            ('Oliver','Male'),('Oscar','Male'),('Raymond','Male'),('Ronald','Male'),
            ('Sebastian','Male'),('Solomon','Male'),('Stanley','Male'),
            ('Victor','Male'),('Vincent','Male'),('Walter','Male'),('Wesley','Male'),
            ('Wilson','Male'),('Zachary','Male'),
            ('Kamau','Male'),('Njoroge','Male'),('Mwangi','Male'),('Kariuki','Male'),
            ('Githinji','Male'),('Kimani','Male'),('Kibet','Male'),('Kipchoge','Male'),
            ('Kiptoo','Male'),('Kipkoech','Male'),('Kiprotich','Male'),
            ('Mutua','Male'),('Musyoka','Male'),('Muema','Male'),('Muthomi','Male'),
            ('Muthee','Male'),('Muriuki','Male'),('Mureithi','Male'),('Mugo','Male'),
            ('Ochieng','Male'),('Otieno','Male'),('Omondi','Male'),('Owino','Male'),
            ('Odongo','Male'),('Onyango','Male'),('Okoth','Male'),
            ('Wekesa','Male'),('Simiyu','Male'),('Barasa','Male'),('Makokha','Male'),
            ('Hassan','Male'),('Hussein','Male'),('Omar','Male'),('Ahmed','Male'),
            ('Mohammed','Male'),('Ali','Male'),('Ibrahim','Male'),('Yusuf','Male'),
            ('Salim','Male'),('Hamisi','Male'),('Rashid','Male'),('Bakari','Male'),
            ('Juma','Male'),('Musa','Male'),('Issa','Male'),
            ('Eric','Male'),('Erick','Male'),('Edwin','Male'),('Elijah','Male'),
            ('Ezekiel','Male'),('Enoch','Male'),('Eliud','Male'),('Elias','Male'),
            ('Felix','Male'),('Frank','Male'),('Franklin','Male'),('Frederick','Male'),
            ('Geoffrey','Male'),('Gerald','Male'),('Gilbert','Male'),('Gordon','Male'),
            ('Gregory','Male'),('Harrison','Male'),('Herbert','Male'),('Hillary','Male'),
            ('Humphrey','Male'),('Ian','Male'),('Jack','Male'),('Jacob','Male'),
            ('Jason','Male'),('Jeremy','Male'),('Jesse','Male'),('Joel','Male'),
            ('Jordan','Male'),('Justin','Male'),('Julius','Male'),
            ('Keith','Male'),('Kelvin','Male'),('Kennedy','Male'),('Ken','Male'),
            ('Laban','Male'),('Lazarus','Male'),('Lewis','Male'),('Linus','Male'),
            ('Mathew','Male'),('Maurice','Male'),('Melvin','Male'),('Milton','Male'),
            ('Morris','Male'),('Newton','Male'),('Norman','Male'),
            ('Phineas','Male'),('Pius','Male'),('Prince','Male'),
            ('Raphael','Male'),('Reuben','Male'),('Rodgers','Male'),('Rogers','Male'),
            ('Ronnie','Male'),('Roy','Male'),('Samson','Male'),('Shadrack','Male'),
            ('Silas','Male'),('Suleiman','Male'),('Terence','Male'),('Terry','Male'),
            ('Tom','Male'),('Tony','Male'),('Trevor','Male'),('Titus','Male'),
            ('Valentine','Male'),('Wycliffe','Male'),('Wilfred','Male'),('Willis','Male'),
            ('Collins','Male'),('Clinton','Male'),('Clement','Male'),('Christopher','Male'),
            ('Calvin','Male'),('Caleb','Male'),('Boniface','Male'),('Benson','Male'),
            ('Bernard','Male'),('Benedict','Male'),('Ben','Male'),
            ('Alex','Male'),('Alexander','Male'),('Alfred','Male'),('Alvin','Male'),
            ('Ambrose','Male'),('Amos','Male'),('Antony','Male'),('Arnold','Male'),
            ('Arthur','Male'),('Augustine','Male'),('Austin','Male'),
            ('Abel','Male'),('Abraham','Male'),('Adam','Male'),('Adrian','Male'),
            ('Albert','Male'),('Allan','Male'),('Allen','Male'),
            ('Dedan','Male'),('Dickson','Male'),('Douglas','Male'),('Duncan','Male'),
            ('Cyrus','Male'),('Cornelius','Male'),('Conrad','Male'),('Cosmas','Male'),
            ('Festus','Male'),('Gideon','Male'),('Godwin','Male'),('Godfrey','Male'),
            ('Hezekiah','Male'),('Hosea','Male'),('Ignatius','Male'),('Isaiah','Male'),
            ('Jeremiah','Male'),('Job','Male'),('Jonah','Male'),
            ('Lameck','Male'),('Levy','Male'),('Lot','Male'),
            ('Micah','Male'),('Mordecai','Male'),('Nahum','Male'),('Nehemiah','Male'),
            ('Nicodemus','Male'),('Noah','Male'),('Obadiah','Male'),('Obed','Male'),
            ('Reginald','Male'),('Renson','Male'),('Shaun','Male'),('Spencer','Male'),
            ('Theodore','Male'),('Tobias','Male'),('Uriah','Male'),
            ('Zadock','Male'),('Zedekiah','Male'),('Zephaniah','Male'),
            ('Elvis','Male'),('Emeka','Male'),
            ('Gichuru','Male'),('Nandwa','Male'),('Wangila','Male'),('Masinde','Male'),
            ('Ogola','Male'),('Ogolla','Male'),
            ('Chris','Male'),('Christian','Male'),('Bruce','Male'),('Brandon','Male'),
            ('Bob','Male'),('Billy','Male'),('Ivan','Male'),('Jake','Male'),
            ('Jefferson','Male'),('Jerome','Male'),('Kelly','Male'),
            ('Livingstone','Male'),('Rex','Male'),('Roman','Male'),('Ruben','Male'),
            ('Tobijah','Male'),('Ulrick','Male'),('Valentin','Male'),
            ('Carol','Female'),
            ('Nalongo','Female'),
            ('Bethy','Female'),
            ('Mabel','Female'),
            ('Veron','Female'),
            ('Abigael','Female'),
            ('Cherotich','Female'),
            ('Sharlet','Female'),
            ('Curie','Female'),
            ('Kezia','Female'),
            ('Eglah','Female'),
            ('Staicy','Female'),
            ('Vanessa','Female'),
            ('Furaha','Female'),
            ('Halola','Female'),
            ('Beth','Female'),
            ('Vallary','Female'),
            ('Elosy','Female'),
            ('Cheryl','Female'),
            ('Anne','Female'),
            ('Dyna','Female'),
            ('Mitchelle','Female'),
            ('Patricia','Female'),
            ('Philister','Female'),
            ('Phelgona','Female'),
            ('Everlyne','Female'),
            ('Victoria','Female'),
            ('KNOWLEDGE','Female'),
            ('Tonny','Male'),
            ('Benard','Male'),
            ('Hawkins','Male'),
            ('Kathimuuri','Male'),
            ('Geofrey','Male'),
            ('Edgar','Male'),
            ('Mabeya','Male'),
            ('Odhiambo','Male'),
            ('Zacheus','Male'),
            ('Neville','Male'),
            ('Gabbs','Male')
         ) AS gn(first_name, gender)
         WHERE LOWER(gn.first_name) = LOWER(
            CASE
                WHEN TRIM(cns.first_name) = '' OR cns.first_name IS NULL
                    THEN SPLIT_PART(cns.full_name, ' ', 1)
                ELSE cns.first_name
            END
         )
         LIMIT 1
        ),
        'N/A'
    )                                                                   AS "Gender",

    -- Phone (clean special characters, return N/A if empty)
    CASE
        WHEN TRIM(
            CASE
                WHEN rp.phone ~ '^\\+?(254|256|255)'
                    THEN '0' || REGEXP_REPLACE(rp.phone, '^\\+?(254|256|255)', '')
                ELSE rp.phone
            END
        ) = '' OR rp.phone IS NULL
            THEN 'N/A'
        ELSE TRIM(
            REGEXP_REPLACE(
                CASE
                    WHEN rp.phone ~ '^\\+?(254|256|255)'
                        THEN '0' || REGEXP_REPLACE(rp.phone, '^\\+?(254|256|255)', '')
                    ELSE rp.phone
                END,
                '[^0-9+]', '', 'g'
            )
        )
    END                                                             AS "Phone",

    -- Product (remove discount text and color suffix)
    CASE
        WHEN pcs.matched_color IS NULL
            THEN TRIM(REGEXP_REPLACE(pcs.full_name, '^\\d+(\\.\\d+)?\\s*KES\\s+discount.*$', '', 'i'))
        WHEN pcs.full_name = pcs.matched_color
            THEN pcs.full_name
        ELSE TRIM(REGEXP_REPLACE(
                LEFT(
                    pcs.full_name,
                    LENGTH(pcs.full_name) - LENGTH(pcs.matched_color)
                ),
                '^\\d+(\\.\\d+)?\\s*KES\\s+discount.*$', '', 'i'
            ))
    END                                                             AS "Product",

    -- Color
    CASE
        WHEN pcs.matched_color IS NULL THEN 'Combo'
        ELSE pcs.matched_color
    END                                                             AS "Color",

    -- Category
    CASE
        WHEN pc.name = 'All' THEN 'Combo'
        ELSE TRIM(REGEXP_REPLACE(pc.name, '^[^/]+/\\s*', ''))
    END                                                             AS "Category",

    -- Location
    CASE
        WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%'
            THEN 'Sinza'
        ELSE INITCAP(
                TRIM(REGEXP_REPLACE(
                    COALESCE(sw.name, sl.complete_name, 'N/A'),
                    '\\s*Shop\\s*', '', 'gi'
                ))
            )
    END                                                             AS "Location",

    -- Unit Price (price per item)
    ROUND(
        CASE
            WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%'
                THEN (pol.price_subtotal_incl / 25) / NULLIF(pol.qty, 0)
            WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Uganda%'
                THEN (pol.price_subtotal_incl / 29) / NULLIF(pol.qty, 0)
            ELSE pol.price_subtotal_incl / NULLIF(pol.qty, 0)
        END,
        2
    )                                                               AS "Price",

    -- Quantity
    pol.qty                                                         AS "Quantity",

    -- Total (Price * Quantity)
    ROUND(
        CASE
            WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Dar-Es-Alam%'
                THEN pol.price_subtotal_incl / 25
            WHEN COALESCE(sw.name, sl.complete_name) ILIKE '%Uganda%'
                THEN pol.price_subtotal_incl / 29
            ELSE pol.price_subtotal_incl
        END,
        2
    )                                                               AS "Total",

    -- Customer Type
    COALESCE(po.customer_type, 'N/A')                              AS "Customer Type"

FROM pos_order po

LEFT JOIN res_partner          rp    ON rp.id    = po.partner_id
LEFT JOIN customer_name_split  cns   ON cns.id   = rp.id
LEFT JOIN pos_order_line       pol   ON pol.order_id = po.id
LEFT JOIN product_product      pp    ON pp.id    = pol.product_id
LEFT JOIN product_template     pt    ON pt.id    = pp.product_tmpl_id
LEFT JOIN product_color_split  pcs   ON pcs.product_tmpl_id = pt.id
LEFT JOIN product_category     pc    ON pc.id    = pt.categ_id
LEFT JOIN pos_session          ps    ON ps.id    = po.session_id
LEFT JOIN pos_config           pconf ON pconf.id = ps.config_id
LEFT JOIN stock_picking_type   spt   ON spt.id   = pconf.picking_type_id
LEFT JOIN stock_warehouse      sw    ON sw.id    = spt.warehouse_id
LEFT JOIN stock_location       sl    ON sl.id    = spt.default_location_src_id

WHERE
    po.state IN ('done', 'paid')
    AND pt.name NOT ILIKE '%Delivery Fee%'
    AND pt.name NOT ILIKE '%Gift Bag%'
    AND pc.name NOT ILIKE '%Pos%'
    AND pol.qty > 0
    AND pt.name NOT ILIKE '%KES discount%'
    AND po.date_order >= CAST(:start_date AS TIMESTAMP)
    AND po.date_order < CAST(:end_date AS TIMESTAMP) + INTERVAL '1 day'

ORDER BY po.date_order DESC;
"""

# Production floor breakdown across 8 stages (materials -> drawn -> cut -> issued
# -> WIP -> in-store -> repairs -> samples), one row per Metric + Product.
# "Bags Cut in Store" is a live balance and intentionally ignores the date range.
PRODUCTION_BREAKDOWN = """
WITH date_range AS (
    SELECT
        CAST(:start_date AS DATE) AS start_date,
        CAST(:end_date AS DATE) AS end_date
),

breakdown AS (

    -- 1. Materials Used (by material product)
    SELECT
        1 AS metric_order,
        'Materials Used' AS metric,
        pt.name AS product,
        SUM(dro.material_required_qty) AS quantity
    FROM denri_drawing_order dro
    LEFT JOIN product_product  pp ON pp.id = dro.material_product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE dro.draw_date BETWEEN dr.start_date AND dr.end_date
      AND dro.state = 'confirmed'
      AND COALESCE(dro.material_required_qty, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 2. Bags Drawn (by bag product)
    SELECT
        2, 'Bags Drawn',
        pt.name,
        SUM(dro.total_bags_drawn)
    FROM denri_drawing_order dro
    LEFT JOIN product_product  pp ON pp.id = dro.bag_product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE dro.draw_date BETWEEN dr.start_date AND dr.end_date
      AND dro.state = 'confirmed'
      AND COALESCE(dro.total_bags_drawn, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 3. Bags Cut (by bag product)
    SELECT
        3, 'Bags Cut',
        pt.name,
        SUM(cb.qty_cut)
    FROM denri_cut_batch cb
    LEFT JOIN product_product  pp ON pp.id = cb.bag_product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE cb.cut_date BETWEEN dr.start_date AND dr.end_date
      AND cb.cancelled_date IS NULL
      AND COALESCE(cb.qty_cut, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 4. Bags Issued (by product)
    SELECT
        4, 'Bags Issued',
        pt.name,
        SUM(bi.qty_issued)
    FROM denri_bags_issued bi
    LEFT JOIN product_product  pp ON pp.id = bi.product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE bi.issue_date BETWEEN dr.start_date AND dr.end_date
      AND COALESCE(bi.active, TRUE) = TRUE
      AND COALESCE(bi.is_return_job, FALSE) = FALSE
      AND COALESCE(bi.is_rework, FALSE) = FALSE
      AND COALESCE(bi.is_control_record, FALSE) = FALSE
      AND COALESCE(bi.exclude_from_kpi, FALSE) = FALSE
      AND COALESCE(bi.qty_issued, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 5. WIP Created (by bag product)
    SELECT
        5, 'WIP Created',
        pt.name,
        SUM(wb.patterns_qty)
    FROM denri_wip_batch wb
    LEFT JOIN product_product  pp ON pp.id = wb.bag_product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE wb.wip_date BETWEEN dr.start_date AND dr.end_date
      AND wb.cancelled_date IS NULL
      AND COALESCE(wb.patterns_qty, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 6. Bags Cut in Store = qty_balance_effective, in-store non-cancelled (live balance, no date filter)
    SELECT
        6, 'Bags Cut in Store',
        pt.name,
        SUM(cb.qty_balance_effective)
    FROM denri_cut_batch cb
    LEFT JOIN product_product  pp ON pp.id = cb.bag_product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE cb.counts_in_store = TRUE
      AND cb.cancelled_date IS NULL
      AND COALESCE(cb.qty_balance_effective, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 7. Repairs (pending total, shop-rows approximation)
    SELECT
        7, 'Repairs',
        pt.name,
        SUM(rp.qty)
    FROM denri_dispatch_repair rp
    LEFT JOIN product_product  pp ON pp.id = rp.product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE rp.report_date BETWEEN dr.start_date AND dr.end_date
      AND COALESCE(rp.is_cancelled, FALSE) = FALSE
      AND rp.shop_id IS NOT NULL
      AND COALESCE(rp.qty, 0) <> 0
    GROUP BY pt.name

    UNION ALL

    -- 8. Samples (by bag product)
    SELECT
        8, 'Samples',
        pt.name,
        SUM(dro.sample_bags_drawn)
    FROM denri_drawing_order dro
    LEFT JOIN product_product  pp ON pp.id = dro.bag_product_id
    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id,
    date_range dr
    WHERE dro.draw_date BETWEEN dr.start_date AND dr.end_date
      AND dro.state = 'confirmed'
      AND COALESCE(dro.sample_bags_drawn, 0) <> 0
    GROUP BY pt.name
)

SELECT
    metric_order,
    metric                       AS "Metric",
    COALESCE(product, 'N/A')     AS "Product",
    ROUND(quantity::NUMERIC, 2)  AS "Quantity"
FROM breakdown
ORDER BY metric_order, "Quantity" DESC;
"""

# Goods in transit to the two international channels (Sinza/Tanzania, Uganda),
# pivoted by bag product with a GRAND TOTAL row.
GOODS_IN_TRANSIT = """
WITH date_range AS (
  SELECT
    CAST(:start_date AS DATE) AS start_date,
    CAST(:end_date AS DATE) AS end_date
),
moves AS (
  SELECT
    COALESCE(pt."name", pp.id::text) AS bag_name,
    CASE
      WHEN rp."name" ILIKE '%Luggageware Uganda%' THEN 'UGANDA'
      ELSE 'SINZA'                       -- Bagware Tanzania = Sinza channel
    END AS dest_name,
    sol.product_uom_qty AS qty,         -- ordered qty; use sol.qty_delivered for delivered
    DATE(so.date_order) AS order_date
  FROM sale_order so
  JOIN sale_order_line sol ON sol.order_id = so.id
  JOIN res_partner rp ON so.partner_id = rp.id
  JOIN product_product pp ON sol.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  CROSS JOIN date_range dr
  WHERE (rp."name" ILIKE '%Bagware Tanzania%' OR rp."name" ILIKE '%Luggageware Uganda%')
    AND so.state IN ('sale','done')
    AND DATE(so.date_order) BETWEEN dr.start_date AND dr.end_date
    AND COALESCE(sol.product_uom_qty,0) <> 0
),
pivoted AS (
  SELECT
    bag_name,
    STRING_AGG(DISTINCT TO_CHAR(order_date, 'YYYY-MM-DD'), ', ' ORDER BY TO_CHAR(order_date, 'YYYY-MM-DD')) AS "Dates",
    SUM(CASE WHEN dest_name = 'SINZA'  THEN qty ELSE 0 END) AS "SINZA",
    SUM(CASE WHEN dest_name = 'UGANDA' THEN qty ELSE 0 END) AS "UGANDA"
  FROM moves
  GROUP BY bag_name
),
combined AS (
  SELECT bag_name, "Dates", "SINZA", "UGANDA", 0 AS sort_order FROM pivoted
  UNION ALL
  SELECT 'GRAND TOTAL', NULL, SUM("SINZA"), SUM("UGANDA"), 1 FROM pivoted
)
SELECT
  "Dates",
  bag_name AS "Product",
  "SINZA",
  "UGANDA",
  ("SINZA" + "UGANDA") AS "TOTAL"
FROM combined
ORDER BY sort_order, bag_name;
"""

# Bags sold pivoted by category (bag style) x store, with per-category subtotal
# rows and a grand total. Wide-format companion to PRODUCT_SALES_BY_SHOP.
BAGS_SOLD_BY_CATEGORY = """
WITH date_params AS (
  SELECT
    CAST(:start_date AS DATE) AS start_date,
    CAST(:end_date AS DATE) AS end_date
),

bag_categories AS (
  SELECT UPPER(category) AS category FROM (VALUES
    ('ACE'),('ADRIAN'),('ALPHA TRAVEL'),('AMARI'),('AMAYA'),
    ('AMORA'),('ANA'),('ANKARA TRAVEL'),('ANTITHEFT'),('ARIA PRO'),
    ('ARIA SLING'),('ARLO MAN BAG'),('ARM BAND'),('ATLAS'),('AURORA'),
    ('AVANA HB'),('BABY BAG'),('BELLO'),('BELT BAG'),('BIG MAN BAG'),
    ('BLISS'),('BONITA'),('BRIEF CASE'),('BUTTERFLY SLING'),('CAIRO BP'),
    ('CALLISTA'),('CATHY HANDBAG'),('CELINE SLING BAG'),('CESS'),('CHARLOTTE'),
    ('CHASE'),('CLAIRE HANDBAG'),('CLEO'),('CODE 3'),('CODE 4 ANKARA'),
    ('CODE 9'),('COLLEGE HB'),('COSMO'),('DARIA'),('DELICA'),
    ('DIAPER BAG'),('DON'),('DOUBLE PRESS'),('ELEKTRA'),('ELLA SLING'),
    ('ELYSE'),('ESMERALDA'),('FABELA'),('FANNY AMAPIANO'),('FANNY PACK'),
    ('FAYOLA'),('FEROZ'),('FOXY'),('GIFT BAG'),('GYM BAG'),
    ('HOOD'),('ICON'),('IMANI'),('JABARI'),('JADE'),
    ('JAMELA'),('JAYDEN MAN'),('JUMBO'),('KAI'),('KANJI'),
    ('KAOS'),('KARINA'),('KATE'),('KAYLA'),('KAZ'),
    ('LADONA'),('LANKA'),('LEGACY'),('LEILA'),('LIAM'),
    ('LITE'),('LOLA'),('LOOP BP'),('LOTUS'),('LUCA'),
    ('LUNA'),('LUNA AMAPIANO'),('LUNCHSET'),('MAKE UP POUCH'),('MAN BAG'),
    ('MANDY HB'),('MARLEY'),('MAYA'),('MEGA'),('MINI MANBAG'),
    ('MINI MAYA'),('MINI SCHOOL'),('MINI UMBRA'),('MINI ZURI'),('MODERN TRAVEL'),
    ('MONAH BP'),('MONTANA'),('MOON BAG'),('MRADI TRAVEL'),('MYSTIQUE'),
    ('NALA'),('NEO MAN'),('NINA'),('NIZANA'),('NOVA'),
    ('NYLA BP'),('OVAL HANDBAG'),('PIONEER'),('POCKET TRAVEL'),('POH HAIRISTIC'),
    ('PRIME'),('REESTO CHEST'),('REMI'),('REO TRAVEL'),('ROZA'),
    ('SAFIRI BP'),('SAFIRI TRAVEL'),('SANTANA'),('SARAI'),('SATCHEL'),
    ('SATIS'),('SAVANNAH SLING'),('SCARLET'),('SCHOOL BAG'),('SCOOBY'),
    ('SHUGLI BACKPACK'),('SIERRA HANDBAG'),('SKYE HB'),('SLEEVE 1'),('SLEEVE 2'),
    ('SPARK'),('SPLASH BACKPACK'),('TAJI'),('TITAN TRAVEL'),('STANDARD TRAVEL'),
    ('TRAVOLTA'),('TRECENTO'),('TRIO MIO'),('TWAIN TRAVEL'),('TYLER'),
    ('UMBRA'),('VAL'),('VANITY'),('VOYAGE'),('WANDER LUXE'),
    ('WASHBAG'),('YARA'),('ZANE MAN'),('ZELUS'),('ZENO'),
    ('ZIARA MAN BAG'),('ZING SLING'),('ZIPPED LUNCHSET'),('ZOEZI'),('ZULA'),('ZURI')
  ) AS t(category)
),

raw_sales AS (
  SELECT
    COALESCE(pt."name", '<<unknown>>') AS product_name,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'starmall')     AS starmall,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'mombasa')      AS mombasa,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'nakuru')       AS nakuru,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'eldoret')      AS eldoret,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'kisumu')       AS kisumu,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'meru')         AS meru,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'thika')        AS thika,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'hazina')       AS hazina,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'kitengela')    AS kitengela,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") IN ('website sales','website','jumia') OR p.session_id IS NULL) AS website,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'nanyuki')      AS nanyuki,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'kakamega')     AS kakamega,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'hilton')       AS hilton,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") IN ('sinza','dar-es-alam')) AS sinza,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'uganda')       AS uganda,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'kisii')        AS kisii,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") IN ('ktda','ktda shop')) AS ktda,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'busia')        AS busia,
    SUM(pl.qty) FILTER (WHERE lower(pc."name") = 'rongai')       AS rongai,
    SUM(pl.qty) AS total
  FROM pos_order p
  CROSS JOIN date_params dp
  JOIN pos_order_line pl ON pl.order_id = p.id
  LEFT JOIN pos_session ps ON p.session_id = ps.id
  LEFT JOIN pos_config pc ON ps.config_id = pc.id
  LEFT JOIN product_product pp ON pl.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  LEFT JOIN product_category pcat ON pcat.id = pt.categ_id
  WHERE p.date_order::date BETWEEN dp.start_date AND dp.end_date
    AND p.state IN ('done', 'paid')
    AND COALESCE(pt."name", '') NOT LIKE '%+%'
    AND COALESCE(pt."name", '') NOT ILIKE '%Delivery Fee%'
    AND COALESCE(pt."name", '') NOT ILIKE '%Gift Bag%'
    AND COALESCE(pt."name", '') NOT ILIKE '%KES discount%'
    AND COALESCE(pcat."name", '') NOT ILIKE '%Pos%'
    AND pl.qty > 0
  GROUP BY product_name
),

categorized AS (
  SELECT
    rs.*,
    (SELECT category FROM bag_categories bc
     WHERE rs.product_name ILIKE bc.category || '%'
     ORDER BY LENGTH(bc.category) DESC LIMIT 1) AS category
  FROM raw_sales rs
),

product_details AS (
  SELECT
    product_name AS bag_name,
    starmall, mombasa, nakuru, eldoret, kisumu, meru, thika,
    hazina, kitengela, website, nanyuki, kakamega, hilton, sinza,
    uganda, kisii, ktda, busia, rongai, total,
    category,
    0 AS sort_priority
  FROM categorized
  WHERE category IS NOT NULL
),

category_totals AS (
  SELECT
    category || ' Total' AS bag_name,
    SUM(starmall) AS starmall,
    SUM(mombasa) AS mombasa,
    SUM(nakuru) AS nakuru,
    SUM(eldoret) AS eldoret,
    SUM(kisumu) AS kisumu,
    SUM(meru) AS meru,
    SUM(thika) AS thika,
    SUM(hazina) AS hazina,
    SUM(kitengela) AS kitengela,
    SUM(website) AS website,
    SUM(nanyuki) AS nanyuki,
    SUM(kakamega) AS kakamega,
    SUM(hilton) AS hilton,
    SUM(sinza) AS sinza,
    SUM(uganda) AS uganda,
    SUM(kisii) AS kisii,
    SUM(ktda) AS ktda,
    SUM(busia) AS busia,
    SUM(rongai) AS rongai,
    SUM(total) AS total,
    category,
    1 AS sort_priority
  FROM categorized
  WHERE category IS NOT NULL
  GROUP BY category
),

grand_total AS (
  SELECT
    'GRAND TOTAL' AS bag_name,
    SUM(starmall) AS starmall,
    SUM(mombasa) AS mombasa,
    SUM(nakuru) AS nakuru,
    SUM(eldoret) AS eldoret,
    SUM(kisumu) AS kisumu,
    SUM(meru) AS meru,
    SUM(thika) AS thika,
    SUM(hazina) AS hazina,
    SUM(kitengela) AS kitengela,
    SUM(website) AS website,
    SUM(nanyuki) AS nanyuki,
    SUM(kakamega) AS kakamega,
    SUM(hilton) AS hilton,
    SUM(sinza) AS sinza,
    SUM(uganda) AS uganda,
    SUM(kisii) AS kisii,
    SUM(ktda) AS ktda,
    SUM(busia) AS busia,
    SUM(rongai) AS rongai,
    SUM(total) AS total,
    NULL AS category,
    2 AS sort_priority
  FROM category_totals
)

SELECT
  bag_name AS "Bag",
  COALESCE(starmall, 0) AS "STARMALL",
  COALESCE(mombasa, 0)  AS "MOMBASA",
  COALESCE(nakuru, 0)   AS "NAKURU",
  COALESCE(eldoret, 0)  AS "ELDORET",
  COALESCE(kisumu, 0)   AS "KISUMU",
  COALESCE(meru, 0)     AS "MERU",
  COALESCE(thika, 0)    AS "THIKA",
  COALESCE(hazina, 0)   AS "HAZINA",
  COALESCE(kitengela, 0)AS "KITENGELA",
  COALESCE(website, 0)  AS "WEBSITE",
  COALESCE(nanyuki, 0)  AS "NANYUKI",
  COALESCE(kakamega, 0) AS "KAKAMEGA",
  COALESCE(hilton, 0)   AS "HILTON",
  COALESCE(sinza, 0)    AS "SINZA",
  COALESCE(uganda, 0)   AS "UGANDA",
  COALESCE(kisii, 0)    AS "KISII",
  COALESCE(ktda, 0)     AS "KTDA",
  COALESCE(busia, 0)    AS "BUSIA",
  COALESCE(rongai, 0)   AS "RONGAI",
  COALESCE(total, 0)    AS "TOTAL",
  category              AS "Category",
  sort_priority
FROM (
  SELECT * FROM product_details
  UNION ALL
  SELECT * FROM category_totals
  UNION ALL
  SELECT * FROM grand_total
) combined
ORDER BY category, sort_priority;
"""

# One row per SHOP + PRODUCT with money sold (not units): SALES AMOUNT is
# untaxed (price_subtotal), TOTAL SALES is tax-inclusive (price_subtotal_incl),
# ACTUAL SALES applies the Uganda/Sinza currency conversion. Masterfile
# products (incl. combos) first, then non-masterfile, each block by TOTAL
# SALES descending.
PRODUCT_SALES_VALUE_BY_SHOP = """
WITH date_range AS (
  SELECT
    CAST(:start_date AS DATE) AS start_date,
    CAST(:end_date AS DATE) AS end_date
),

master_order_raw AS (
  SELECT name, ord
  FROM UNNEST(ARRAY[
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
    'Gift Bag A3','Gift Bag A4','Gift Bag A5',
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
    'Zuri Chocolate','Zuri Yellow','Zuri Maroon','Zuri Amber','Zuri Grey','Zuri Dark Brown'
  ]) WITH ORDINALITY AS t(name, ord)
),

master_order AS (
  SELECT DISTINCT ON (UPPER(TRIM(name)))
    UPPER(TRIM(name)) AS product_key,
    ord               AS sort_order
  from master_order_raw
  ORDER BY UPPER(TRIM(name)), ord
),

shop_sales AS (
  SELECT
    CASE
      WHEN lower(pc."name") IN ('website sales','website','jumia') OR p.session_id IS NULL THEN 'WEBSITE'
      WHEN lower(pc."name") IN ('sinza','dar-es-alam')             THEN 'SINZA'
      WHEN lower(pc."name") IN ('ktda','ktda shop')                THEN 'KTDA'
      ELSE UPPER(pc."name")
    END AS shop,
    COALESCE(pt."name", '<<unknown>>') AS product_name,
    SUM(pl.qty)                 AS units_sold,
    SUM(pl.price_subtotal)      AS sales_amount,
    SUM(pl.price_subtotal_incl) AS total_sales,
    MAX(CASE WHEN COALESCE(pt.is_combo, FALSE) = TRUE
             OR  COALESCE(pt."name", '') LIKE '%+%'
             THEN 1 ELSE 0 END) AS combo_flag
  FROM pos_order p
  JOIN pos_order_line pl ON pl.order_id = p.id
  LEFT JOIN pos_session ps ON p.session_id = ps.id
  LEFT JOIN pos_config pc ON ps.config_id = pc.id
  LEFT JOIN product_product pp ON pl.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  LEFT JOIN product_category pcat ON pcat.id = pt.categ_id
  CROSS JOIN date_range dr
  WHERE p.date_order::date BETWEEN dr.start_date AND dr.end_date
    AND p.state IN ('done', 'paid')
    AND (
          COALESCE(pt."name", '') NOT LIKE '%+%'
          OR COALESCE(pt.is_combo, FALSE) = TRUE
        )
    AND COALESCE(pt."name", '') NOT ILIKE '%Delivery Fee%'
    AND COALESCE(pt."name", '') NOT ILIKE '%Gift Bag%'
    AND COALESCE(pt."name", '') NOT ILIKE '%KES discount%'
    AND COALESCE(pcat."name", '') NOT ILIKE '%Pos%'
    AND pl.qty > 0
  GROUP BY 1, 2
  HAVING SUM(pl.price_subtotal_incl) <> 0
),

tagged AS (
  SELECT
    ss.shop,
    ss.product_name,
    ss.units_sold,
    ss.sales_amount,
    ss.total_sales,
    CASE ss.shop
      WHEN 'UGANDA' THEN ss.total_sales / 29.0
      WHEN 'SINZA'  THEN ss.total_sales / 25.0
      ELSE ss.total_sales
    END AS actual_sales,
    CASE WHEN ss.combo_flag = 1 OR mo.product_key IS NOT NULL THEN 0 ELSE 1 END AS section,
    ss.combo_flag AS combo_rank,
    0 AS row_type
  FROM shop_sales ss
  LEFT JOIN master_order mo
    ON mo.product_key = UPPER(TRIM(ss.product_name))
),

section_totals AS (
  SELECT
    '' AS shop,
    CASE section
      WHEN 0 THEN 'MASTERFILE TOTAL'
      ELSE        'NON-MASTERFILE TOTAL'
    END AS product_name,
    SUM(units_sold)   AS units_sold,
    SUM(sales_amount) AS sales_amount,
    SUM(total_sales)  AS total_sales,
    SUM(actual_sales) AS actual_sales,
    section,
    0 AS combo_rank,
    1 AS row_type
  FROM tagged
  GROUP BY section
)

SELECT
  shop         AS "SHOP",
  product_name AS "PRODUCT",
  units_sold   AS "UNITS SOLD",
  ROUND(sales_amount, 2) AS "SALES AMOUNT",
  ROUND(total_sales,  2) AS "TOTAL SALES",
  ROUND(actual_sales, 2) AS "ACTUAL SALES"
FROM (
  SELECT * FROM tagged
  UNION ALL
  SELECT * FROM section_totals
) combined
ORDER BY
  section,
  row_type,
  combo_rank,
  total_sales DESC,
  product_name,
  shop;
"""

# Live on-hand stock by warehouse location x product. No date range — this is
# a current-state snapshot of stock_quant, not a period-filtered movement.
STOCK_LEVELS = """
SELECT
  sl.complete_name                    AS "Location",
  COALESCE(pt."name", pp.id::text)    AS "Product",
  SUM(sq.quantity)                    AS "Quantity"
FROM stock_quant sq
JOIN stock_location sl ON sq.location_id = sl.id
JOIN product_product pp ON sq.product_id = pp.id
LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
WHERE sl.usage = 'internal'
  AND (
       sl.complete_name ILIKE 'STAR/Stock%'  OR sl.complete_name ILIKE 'MSA/Stock%'
    OR sl.complete_name ILIKE 'NAKS/Stock%'  OR sl.complete_name ILIKE 'ELD/Stock%'
    OR sl.complete_name ILIKE 'KSM/Stock%'   OR sl.complete_name ILIKE 'MERU/Stock%'
    OR sl.complete_name ILIKE 'THK/Stock%'   OR sl.complete_name ILIKE 'HAZ/Stock%'
    OR sl.complete_name ILIKE 'KITE/Stock%'  OR sl.complete_name ILIKE 'NAN/Stock%'
    OR sl.complete_name ILIKE 'KAK/Stock%'   OR sl.complete_name ILIKE 'HTN/Stock%'
    OR sl.complete_name ILIKE 'DAR/Stock%'   OR sl.complete_name ILIKE 'UG/Stock%'
    OR sl.complete_name ILIKE 'KSI/Stock%'   OR sl.complete_name ILIKE 'KTDA/Stock%'
    OR sl.complete_name ILIKE 'BUSIA/Stock%' OR sl.complete_name ILIKE 'RONG/Stock%'
    OR sl.complete_name ILIKE 'CBD/Stock%'
    OR sl.complete_name ILIKE 'WEB/Stock%' OR sl.complete_name ILIKE '%WEBSITE%'
  )
  AND COALESCE(pt."name", '') NOT ILIKE '%+%'          -- exclude combo/bundle products
  AND COALESCE(pt."name", '') NOT ILIKE '% or %'       -- exclude "X or Y" pick-one bundles
  AND COALESCE(pt."name", '') NOT ILIKE '%Buy%Get%'    -- exclude "Buy X Get Y Free" bundles
GROUP BY sl.complete_name, COALESCE(pt."name", pp.id::text)
ORDER BY "Location", "Product";
"""

# Combined distribution report: stock moves (FINWH + CBD inventory transfers,
# shop transit dispatches, internal CBD<->KTDA moves) plus sales-order
# dispatch to Sinza/Uganda, pivoted by destination with product-family
# subtotals and a grand total.
DISPATCH_COMBINED = """
WITH params AS (
  SELECT
    CAST(:start_date AS DATE) AS start_date,
    CAST(:end_date AS DATE) AS end_date
),

code_mapping AS (
  SELECT 'STAR' AS code, 'STARMALL' AS full_name
  UNION ALL SELECT 'STARMALL', 'STARMALL'
  UNION ALL SELECT 'MSA', 'MOMBASA'
  UNION ALL SELECT 'MOMBASA', 'MOMBASA'
  UNION ALL SELECT 'NAKS', 'NAKURU'
  UNION ALL SELECT 'NAKURU', 'NAKURU'
  UNION ALL SELECT 'ELD', 'ELDORET'
  UNION ALL SELECT 'ELDORET', 'ELDORET'
  UNION ALL SELECT 'KSM', 'KISUMU'
  UNION ALL SELECT 'KISUMU', 'KISUMU'
  UNION ALL SELECT 'MERU', 'MERU'
  UNION ALL SELECT 'THK', 'THIKA'
  UNION ALL SELECT 'THIKA', 'THIKA'
  UNION ALL SELECT 'HAZ', 'HAZINA'
  UNION ALL SELECT 'HAZINA', 'HAZINA'
  UNION ALL SELECT 'KITE', 'KITENGELA'
  UNION ALL SELECT 'KITENGELA', 'KITENGELA'
  UNION ALL SELECT 'RONG', 'RONGAI'
  UNION ALL SELECT 'RONGAI', 'RONGAI'
  UNION ALL SELECT 'NAN', 'NANYUKI'
  UNION ALL SELECT 'NANYUKI', 'NANYUKI'
  UNION ALL SELECT 'KAK', 'KAKAMEGA'
  UNION ALL SELECT 'KAKAMEGA', 'KAKAMEGA'
  UNION ALL SELECT 'HTN', 'HILTON'
  UNION ALL SELECT 'HILTON', 'HILTON'
  UNION ALL SELECT 'DAR', 'SINZA'
  UNION ALL SELECT 'SINZA', 'SINZA'
  UNION ALL SELECT 'UG', 'UGANDA'
  UNION ALL SELECT 'UGANDA', 'UGANDA'
  UNION ALL SELECT 'KSI', 'KISII'
  UNION ALL SELECT 'KISII', 'KISII'
  UNION ALL SELECT 'KTDA', 'KTDA'
  UNION ALL SELECT 'CBD', 'KTDA'
  UNION ALL SELECT 'BUSIA', 'BUSIA'
),

-- STREAM 1 — FINWH INVENTORY MOVES
finwh_inventory AS (
  SELECT
    COALESCE(pt."name", pp.id::text) AS bag_name,
    COALESCE(
      cm.full_name,
      CASE
        WHEN dest.complete_name ILIKE '%CBD%' OR UPPER(dest."name") IN ('CBD', 'CBD/STOCK', 'KTDA') THEN 'KTDA'
        WHEN dest.complete_name ILIKE '%RONG%' OR UPPER(dest."name") IN ('RONGAI', 'RONG/STOCK') THEN 'RONGAI'
        WHEN UPPER(dest."name") = 'STARMALL' THEN 'STARMALL'
        WHEN UPPER(dest."name") = 'MOMBASA' THEN 'MOMBASA'
        WHEN UPPER(dest."name") = 'NAKURU' THEN 'NAKURU'
        WHEN UPPER(dest."name") = 'ELDORET' THEN 'ELDORET'
        WHEN UPPER(dest."name") = 'KISUMU' THEN 'KISUMU'
        WHEN UPPER(dest."name") = 'MERU' THEN 'MERU'
        WHEN UPPER(dest."name") = 'THIKA' THEN 'THIKA'
        WHEN UPPER(dest."name") = 'HAZINA' THEN 'HAZINA'
        WHEN UPPER(dest."name") = 'KITENGELA' THEN 'KITENGELA'
        WHEN UPPER(dest."name") = 'NANYUKI' THEN 'NANYUKI'
        WHEN UPPER(dest."name") = 'KAKAMEGA' THEN 'KAKAMEGA'
        WHEN UPPER(dest."name") = 'HILTON' THEN 'HILTON'
        WHEN UPPER(dest."name") = 'SINZA' THEN 'SINZA'
        WHEN UPPER(dest."name") = 'UGANDA' THEN 'UGANDA'
        WHEN UPPER(dest."name") = 'KISII' THEN 'KISII'
        WHEN UPPER(dest."name") = 'BUSIA' THEN 'BUSIA'
        ELSE dest."name"
      END
    ) AS dest_name,
    m.product_qty AS qty,
    m.state AS move_state,
    DATE(m."date") AS move_date
  FROM stock_move m
  JOIN stock_location src ON m.location_id = src.id
  JOIN stock_location dest ON m.location_dest_id = dest.id
  JOIN product_product pp ON m.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  LEFT JOIN code_mapping cm ON UPPER(SPLIT_PART(COALESCE(m.reference, m."name"), '/', 1)) = cm.code
  CROSS JOIN params p
  WHERE (UPPER(src."name") IN ('FINWH', 'FINWH/STOCK') OR src.complete_name ILIKE '%FINWH%')
    AND (
      UPPER(dest."name") IN (
        'STARMALL','MOMBASA','NAKURU','ELDORET','KISUMU','MERU','THIKA','HAZINA',
        'KITENGELA','WEBSITE','NANYUKI','KAKAMEGA','HILTON','SINZA','UGANDA',
        'KISII','CBD','CBD/STOCK','BUSIA','RONGAI'
      )
      OR dest.complete_name ILIKE '%CBD%'
      OR dest.complete_name ILIKE '%RONG%'
      OR UPPER(SPLIT_PART(COALESCE(m.reference, m."name"), '/', 1)) IN (
        'STAR','MSA','NAKS','ELD','KSM','MERU','THK','HAZ','KITE','RONG','NAN',
        'KAK','HTN','DAR','UG','KSI','KTDA','BUSIA','CBD','STARMALL','MOMBASA',
        'NAKURU','ELDORET','KISUMU','THIKA','HAZINA','KITENGELA','RONGAI',
        'NANYUKI','KAKAMEGA','HILTON','SINZA','UGANDA','KISII'
      )
    )
    AND DATE(m."date") BETWEEN p.start_date AND p.end_date
    AND EXTRACT(DOW FROM m."date") != 0
),
finwh_filtered AS (
  SELECT bag_name, dest_name, qty, move_date, NULL::int AS dedup_key
  FROM finwh_inventory
  WHERE (dest_name IN ('SINZA', 'UGANDA') AND move_state = 'done')
     OR (dest_name NOT IN ('SINZA', 'UGANDA') AND move_state != 'cancel')
),

-- STREAM 2 — SHOP TRANSIT DISPATCHES
transit_moves AS (
  SELECT
    COALESCE(pt."name", pp.id::text) AS bag_name,
    CASE
      WHEN UPPER(s."name") = 'KTDA SHOP' OR s."name" ILIKE '%CBD%' THEN 'KTDA'
      WHEN s."name" ILIKE '%RONG%' THEN 'RONGAI'
      WHEN UPPER(s."name") = 'STARMALL' THEN 'STARMALL'
      WHEN UPPER(s."name") = 'MOMBASA' THEN 'MOMBASA'
      WHEN UPPER(s."name") = 'NAKURU' THEN 'NAKURU'
      WHEN UPPER(s."name") = 'ELDORET' THEN 'ELDORET'
      WHEN UPPER(s."name") = 'KISUMU' THEN 'KISUMU'
      WHEN UPPER(s."name") = 'MERU' THEN 'MERU'
      WHEN UPPER(s."name") = 'THIKA' THEN 'THIKA'
      WHEN UPPER(s."name") = 'HAZINA' THEN 'HAZINA'
      WHEN UPPER(s."name") = 'KITENGELA' THEN 'KITENGELA'
      WHEN UPPER(s."name") = 'NANYUKI' THEN 'NANYUKI'
      WHEN UPPER(s."name") = 'KAKAMEGA' THEN 'KAKAMEGA'
      WHEN UPPER(s."name") = 'HILTON' THEN 'HILTON'
      WHEN UPPER(s."name") = 'SINZA' THEN 'SINZA'
      WHEN UPPER(s."name") = 'UGANDA' THEN 'UGANDA'
      WHEN UPPER(s."name") = 'KISII' THEN 'KISII'
      WHEN UPPER(s."name") = 'BUSIA' THEN 'BUSIA'
      ELSE s."name"
    END AS dest_name,
    l.qty_dispatched AS qty,
    t.state AS transit_state,
    DATE(t.dispatch_date) AS move_date
  FROM denri_dispatch_transit_line l
  JOIN denri_dispatch_transit t ON l.transit_id = t.id
  JOIN denri_dispatch_shop s ON t.shop_id = s.id
  JOIN product_product pp ON l.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  CROSS JOIN params p
  WHERE (
      UPPER(s."name") IN (
        'STARMALL','MOMBASA','NAKURU','ELDORET','KISUMU','MERU','THIKA','HAZINA',
        'KITENGELA','WEBSITE','NANYUKI','KAKAMEGA','HILTON','SINZA','UGANDA',
        'KISII','KTDA SHOP','BUSIA','RONGAI'
      )
      OR s."name" ILIKE '%CBD%'
      OR s."name" ILIKE '%RONG%'
    )
    AND DATE(t.dispatch_date) BETWEEN p.start_date AND p.end_date
    AND EXTRACT(DOW FROM t.dispatch_date) != 0
),
transit_filtered AS (
  SELECT bag_name, dest_name, qty, move_date, NULL::int AS dedup_key
  FROM transit_moves
  WHERE (dest_name IN ('SINZA', 'UGANDA') AND transit_state = 'done')
     OR (dest_name NOT IN ('SINZA', 'UGANDA'))
),

-- STREAM 3 — CBD INVENTORY MOVES (only 'done' moves)
cbd_inventory AS (
  SELECT
    COALESCE(pt."name", pp.id::text) AS bag_name,
    COALESCE(
      cm.full_name,
      CASE
        WHEN dest.complete_name ILIKE '%CBD%' OR UPPER(dest."name") IN ('CBD', 'CBD/STOCK', 'KTDA') THEN 'KTDA'
        WHEN dest.complete_name ILIKE '%RONG%' OR UPPER(dest."name") IN ('RONGAI', 'RONG/STOCK') THEN 'RONGAI'
        WHEN UPPER(dest."name") = 'STARMALL' THEN 'STARMALL'
        WHEN UPPER(dest."name") = 'MOMBASA' THEN 'MOMBASA'
        WHEN UPPER(dest."name") = 'NAKURU' THEN 'NAKURU'
        WHEN UPPER(dest."name") = 'ELDORET' THEN 'ELDORET'
        WHEN UPPER(dest."name") = 'KISUMU' THEN 'KISUMU'
        WHEN UPPER(dest."name") = 'MERU' THEN 'MERU'
        WHEN UPPER(dest."name") = 'THIKA' THEN 'THIKA'
        WHEN UPPER(dest."name") = 'HAZINA' THEN 'HAZINA'
        WHEN UPPER(dest."name") = 'KITENGELA' THEN 'KITENGELA'
        WHEN UPPER(dest."name") = 'NANYUKI' THEN 'NANYUKI'
        WHEN UPPER(dest."name") = 'KAKAMEGA' THEN 'KAKAMEGA'
        WHEN UPPER(dest."name") = 'HILTON' THEN 'HILTON'
        WHEN UPPER(dest."name") = 'SINZA' THEN 'SINZA'
        WHEN UPPER(dest."name") = 'UGANDA' THEN 'UGANDA'
        WHEN UPPER(dest."name") = 'KISII' THEN 'KISII'
        WHEN UPPER(dest."name") = 'BUSIA' THEN 'BUSIA'
        ELSE dest."name"
      END
    ) AS dest_name,
    m.product_qty AS qty,
    m.state AS move_state,
    DATE(m."date") AS move_date
  FROM stock_move m
  JOIN stock_location src ON m.location_id = src.id
  JOIN stock_location dest ON m.location_dest_id = dest.id
  JOIN product_product pp ON m.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  LEFT JOIN code_mapping cm ON UPPER(SPLIT_PART(COALESCE(m.reference, m."name"), '/', 1)) = cm.code
  CROSS JOIN params p
  WHERE (UPPER(src."name") IN ('CBD', 'CBD/STOCK') OR src.complete_name ILIKE '%CBD%')
    AND (
      UPPER(dest."name") IN (
        'STARMALL','MOMBASA','NAKURU','ELDORET','KISUMU','MERU','THIKA','HAZINA',
        'KITENGELA','WEBSITE','NANYUKI','KAKAMEGA','HILTON','SINZA','UGANDA',
        'KISII','CBD','CBD/STOCK','BUSIA','RONGAI'
      )
      OR dest.complete_name ILIKE '%CBD%'
      OR dest.complete_name ILIKE '%RONG%'
      OR UPPER(SPLIT_PART(COALESCE(m.reference, m."name"), '/', 1)) IN (
        'STAR','MSA','NAKS','ELD','KSM','MERU','THK','HAZ','KITE','RONG','NAN',
        'KAK','HTN','DAR','UG','KSI','KTDA','BUSIA','CBD','STARMALL','MOMBASA',
        'NAKURU','ELDORET','KISUMU','THIKA','HAZINA','KITENGELA','RONGAI',
        'NANYUKI','KAKAMEGA','HILTON','SINZA','UGANDA','KISII'
      )
    )
    AND DATE(m."date") BETWEEN p.start_date AND p.end_date
    AND EXTRACT(DOW FROM m."date") != 0
),
cbd_filtered AS (
  SELECT bag_name, dest_name, qty, move_date, NULL::int AS dedup_key
  FROM cbd_inventory
  WHERE move_state = 'done'
    AND dest_name NOT IN ('KTDA', 'WEBSITE')
),

-- STREAM 4 — INTERNAL CBD <-> KTDA MOVES
ktda_internal AS (
  SELECT
    COALESCE(pt."name", pp.id::text) AS bag_name,
    'KTDA NEW' AS dest_name,
    m.product_qty AS qty,
    DATE(m."date") AS move_date,
    m.id AS dedup_key
  FROM stock_move m
  JOIN stock_location src ON m.location_id = src.id
  JOIN stock_location dest ON m.location_dest_id = dest.id
  JOIN product_product pp ON m.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  CROSS JOIN params p
  WHERE (src.complete_name ILIKE '%CBD%' OR src.complete_name ILIKE '%KTDA%'
         OR UPPER(src."name") IN ('CBD', 'CBD/STOCK', 'KTDA', 'KTDA SHOP'))
    AND (dest.complete_name ILIKE '%CBD%' OR dest.complete_name ILIKE '%KTDA%'
         OR UPPER(dest."name") IN ('CBD', 'CBD/STOCK', 'KTDA', 'KTDA SHOP'))
    AND src.id != dest.id
    AND DATE(m."date") BETWEEN p.start_date AND p.end_date
    AND m.state != 'cancel'
),

-- STREAM 5 — SALES-ORDER DISPATCH (Bagware Tanzania / Luggageware Uganda)
sale_dispatch AS (
  SELECT
    COALESCE(pt."name", pp.id::text) AS bag_name,
    CASE
      WHEN rp."name" ILIKE '%Luggageware Uganda%' THEN 'UGANDA'
      ELSE 'SINZA'
    END AS dest_name,
    sol.product_uom_qty AS qty,
    DATE(so.date_order) AS move_date,
    NULL::int AS dedup_key
  FROM sale_order so
  JOIN sale_order_line sol ON sol.order_id = so.id
  JOIN res_partner rp ON so.partner_id = rp.id
  JOIN product_product pp ON sol.product_id = pp.id
  LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
  CROSS JOIN params p
  WHERE (rp."name" ILIKE '%Bagware Tanzania%' OR rp."name" ILIKE '%Luggageware Uganda%')
    AND so.state IN ('sale','done')
    AND DATE(so.date_order) BETWEEN p.start_date AND p.end_date
    AND COALESCE(sol.product_uom_qty,0) <> 0
),

all_moves AS (
  SELECT bag_name, dest_name, qty, move_date, dedup_key FROM finwh_filtered
  UNION ALL
  SELECT bag_name, dest_name, qty, move_date, dedup_key FROM transit_filtered WHERE dest_name != 'SINZA'
  UNION ALL
  SELECT bag_name, dest_name, qty, move_date, dedup_key FROM cbd_filtered
  UNION ALL
  SELECT bag_name, dest_name, qty, move_date, dedup_key FROM ktda_internal
  UNION ALL
  SELECT bag_name, dest_name, qty, move_date, dedup_key FROM sale_dispatch
),

distinct_moves AS (
  SELECT DISTINCT bag_name, dest_name, qty, move_date, dedup_key
  FROM all_moves
),

aggregated_moves AS (
  SELECT bag_name, dest_name, SUM(qty) AS qty
  FROM distinct_moves
  GROUP BY bag_name, dest_name
),

pivoted_detail AS (
  SELECT
    bag_name,
    SUM(CASE WHEN dest_name = 'STARMALL' THEN qty ELSE 0 END)   AS "STARMALL",
    SUM(CASE WHEN dest_name = 'MOMBASA' THEN qty ELSE 0 END)    AS "MOMBASA",
    SUM(CASE WHEN dest_name = 'NAKURU' THEN qty ELSE 0 END)     AS "NAKURU",
    SUM(CASE WHEN dest_name = 'ELDORET' THEN qty ELSE 0 END)    AS "ELDORET",
    SUM(CASE WHEN dest_name = 'KISUMU' THEN qty ELSE 0 END)     AS "KISUMU",
    SUM(CASE WHEN dest_name = 'MERU' THEN qty ELSE 0 END)       AS "MERU",
    SUM(CASE WHEN dest_name = 'THIKA' THEN qty ELSE 0 END)      AS "THIKA",
    SUM(CASE WHEN dest_name = 'HAZINA' THEN qty ELSE 0 END)     AS "HAZINA",
    SUM(CASE WHEN dest_name = 'KITENGELA' THEN qty ELSE 0 END)  AS "KITENGELA",
    SUM(CASE WHEN dest_name = 'WEBSITE' THEN qty ELSE 0 END)    AS "WEBSITE",
    SUM(CASE WHEN dest_name = 'NANYUKI' THEN qty ELSE 0 END)    AS "NANYUKI",
    SUM(CASE WHEN dest_name = 'KAKAMEGA' THEN qty ELSE 0 END)   AS "KAKAMEGA",
    SUM(CASE WHEN dest_name = 'HILTON' THEN qty ELSE 0 END)     AS "HILTON",
    SUM(CASE WHEN dest_name = 'SINZA' THEN qty ELSE 0 END)      AS "SINZA",
    SUM(CASE WHEN dest_name = 'UGANDA' THEN qty ELSE 0 END)     AS "UGANDA",
    SUM(CASE WHEN dest_name = 'KISII' THEN qty ELSE 0 END)      AS "KISII",
    SUM(CASE WHEN dest_name = 'KTDA' THEN qty ELSE 0 END)       AS "KTDA",
    SUM(CASE WHEN dest_name = 'KTDA NEW' THEN qty ELSE 0 END)   AS "KTDA NEW",
    SUM(CASE WHEN dest_name = 'BUSIA' THEN qty ELSE 0 END)      AS "BUSIA",
    SUM(CASE WHEN dest_name = 'RONGAI' THEN qty ELSE 0 END)     AS "RONGAI"
  FROM aggregated_moves
  GROUP BY bag_name
),

family_map AS (
  SELECT DISTINCT bag_name, SPLIT_PART(bag_name, ' ', 1) AS family
  FROM pivoted_detail
),
family_subtotals AS (
  SELECT
    f.family || ' TOTAL' AS bag_name,
    SUM(p."STARMALL")   AS "STARMALL",
    SUM(p."MOMBASA")    AS "MOMBASA",
    SUM(p."NAKURU")     AS "NAKURU",
    SUM(p."ELDORET")    AS "ELDORET",
    SUM(p."KISUMU")     AS "KISUMU",
    SUM(p."MERU")       AS "MERU",
    SUM(p."THIKA")      AS "THIKA",
    SUM(p."HAZINA")     AS "HAZINA",
    SUM(p."KITENGELA")  AS "KITENGELA",
    SUM(p."WEBSITE")    AS "WEBSITE",
    SUM(p."NANYUKI")    AS "NANYUKI",
    SUM(p."KAKAMEGA")   AS "KAKAMEGA",
    SUM(p."HILTON")     AS "HILTON",
    SUM(p."SINZA")      AS "SINZA",
    SUM(p."UGANDA")     AS "UGANDA",
    SUM(p."KISII")      AS "KISII",
    SUM(p."KTDA")       AS "KTDA",
    SUM(p."KTDA NEW")   AS "KTDA NEW",
    SUM(p."BUSIA")      AS "BUSIA",
    SUM(p."RONGAI")     AS "RONGAI"
  FROM pivoted_detail p
  JOIN family_map f ON p.bag_name = f.bag_name
  GROUP BY f.family
),
grand_total AS (
  SELECT
    'GRAND TOTAL' AS bag_name,
    SUM("STARMALL")   AS "STARMALL",
    SUM("MOMBASA")    AS "MOMBASA",
    SUM("NAKURU")     AS "NAKURU",
    SUM("ELDORET")    AS "ELDORET",
    SUM("KISUMU")     AS "KISUMU",
    SUM("MERU")       AS "MERU",
    SUM("THIKA")      AS "THIKA",
    SUM("HAZINA")     AS "HAZINA",
    SUM("KITENGELA")  AS "KITENGELA",
    SUM("WEBSITE")    AS "WEBSITE",
    SUM("NANYUKI")    AS "NANYUKI",
    SUM("KAKAMEGA")   AS "KAKAMEGA",
    SUM("HILTON")     AS "HILTON",
    SUM("SINZA")      AS "SINZA",
    SUM("UGANDA")     AS "UGANDA",
    SUM("KISII")      AS "KISII",
    SUM("KTDA")       AS "KTDA",
    SUM("KTDA NEW")   AS "KTDA NEW",
    SUM("BUSIA")      AS "BUSIA",
    SUM("RONGAI")     AS "RONGAI"
  FROM pivoted_detail
),
combined AS (
  SELECT
    bag_name,
    "STARMALL","MOMBASA","NAKURU","ELDORET","KISUMU","MERU","THIKA","HAZINA",
    "KITENGELA","WEBSITE","NANYUKI","KAKAMEGA","HILTON","SINZA","UGANDA",
    "KISII","KTDA","KTDA NEW","BUSIA","RONGAI",
    SPLIT_PART(bag_name, ' ', 1) AS family,
    0 AS sort_order
  FROM pivoted_detail
  UNION ALL
  SELECT
    bag_name,
    "STARMALL","MOMBASA","NAKURU","ELDORET","KISUMU","MERU","THIKA","HAZINA",
    "KITENGELA","WEBSITE","NANYUKI","KAKAMEGA","HILTON","SINZA","UGANDA",
    "KISII","KTDA","KTDA NEW","BUSIA","RONGAI",
    bag_name AS family,
    1 AS sort_order
  FROM family_subtotals
  UNION ALL
  SELECT
    bag_name,
    "STARMALL","MOMBASA","NAKURU","ELDORET","KISUMU","MERU","THIKA","HAZINA",
    "KITENGELA","WEBSITE","NANYUKI","KAKAMEGA","HILTON","SINZA","UGANDA",
    "KISII","KTDA","KTDA NEW","BUSIA","RONGAI",
    '~~~~' AS family,
    2 AS sort_order
  FROM grand_total
)

SELECT
  bag_name AS "Product",
  "STARMALL","MOMBASA","NAKURU","ELDORET","KISUMU","MERU","THIKA","HAZINA",
  "KITENGELA","WEBSITE","NANYUKI","KAKAMEGA","HILTON","SINZA","UGANDA",
  "KISII","KTDA","KTDA NEW","BUSIA","RONGAI",
  ("STARMALL"+"MOMBASA"+"NAKURU"+"ELDORET"+"KISUMU"+"MERU"+"THIKA"+"HAZINA"+
   "KITENGELA"+"WEBSITE"+"NANYUKI"+"KAKAMEGA"+"HILTON"+"SINZA"+"UGANDA"+
   "KISII"+"KTDA"+"KTDA NEW"+"BUSIA"+"RONGAI") AS "TOTAL",
  family AS "Family",
  sort_order
FROM combined
ORDER BY family, sort_order, bag_name;
"""
