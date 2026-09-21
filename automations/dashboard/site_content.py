"""Industry content packs and the composer that turns a reply into a full site.

The first version of the generator pasted the client's answers into five
sections and stopped. A freight forwarder and a dentist came out with the same
page, three cards deep, and it read as a form dump rather than a website.

This module is the fix. Each industry pack carries the sections a business of
that kind actually needs - the services it sells, the reasons people choose one
over another, how the work runs, and the questions customers ask - written as
draft copy in the voice of that trade. The client's own answers are laid over
the top: what they said always wins, and the pack fills the gaps that would
otherwise be empty sections.

Where the line sits, deliberately:

* Descriptive copy is generated. "Full and part container loads on the routes
  you use" describes a service category, and every business in it offers that.
* Factual claims are never generated. No years in business, no job counts, no
  certifications, no testimonials, no client names. Those appear only if the
  client stated them, because a website that invents them is a liability.

Everything produced here is a draft for review, and the site's notes say which
sections came from answers and which came from the pack.
"""
import re

# ══════════════════════════════════════════════════════════════════════════════
# Industry packs
# ══════════════════════════════════════════════════════════════════════════════
# keywords : matched against the request title and every answer, scored
# stock    : which folder of the shared image library to draw from
# template : the page shape from site_builder.TEMPLATES
# services : (title, one concrete sentence)
# why      : (title, one concrete sentence) - reasons to choose them
# steps    : (title, one sentence) - how an engagement runs
# faq      : (question, answer)
# serves   : the sectors or customer types, used as ticked points

INDUSTRIES = {
    'logistics': {
        'label': 'Freight & logistics',
        'stock': 'logistics', 'template': 'corporate',
        'palette': 'ocean', 'font': 'modern',
        'keywords': ['freight', 'logistics', 'forwarding', 'clearing', 'customs',
                     'container', 'shipping', 'import', 'export', 'warehous',
                     'courier', 'haulage', 'cargo', 'consignment', 'bill of lading'],
        'services': [
            ('Ocean freight',
             'Full and part container loads on the routes you actually ship.'),
            ('Air freight',
             'For the consignments that cannot wait for a vessel.'),
            ('Customs clearing',
             'Entries prepared and lodged so cargo is not held at the port.'),
            ('Road transport and delivery',
             'From the port or depot to the door, anywhere in the country.'),
            ('Warehousing and distribution',
             'Short and long-term storage, with stock picked and dispatched.'),
            ('Documentation and cargo insurance',
             'Paperwork checked before it is filed, and cover arranged with '
             'the shipment rather than after it.'),
        ],
        'why': [
            ('One contact per shipment',
             'The person who quoted it is the person who tracks it.'),
            ('Clearing handled in-house',
             'Nothing waits on a third party for a signature.'),
            ('All-in costs quoted up front',
             'Including the port and handling charges that get left off.'),
            ('Reachable outside office hours',
             'Vessels and flights do not keep to a working day.'),
        ],
        'steps': [
            ('Send us the details',
             'Origin, destination, weight and what it is. That is enough to quote.'),
            ('You get a written rate',
             'Landed cost, not a freight rate with surprises after it.'),
            ('We book and clear',
             'Carrier booked, entry lodged, documents checked.'),
            ('Delivered and accounted for',
             'Proof of delivery and a closed file you can audit.'),
        ],
        'faq': [
            ('How quickly can you quote?',
             'Same working day for standard routes, once we know the weight, '
             'dimensions and commodity.'),
            ('Do you handle customs clearing yourselves?',
             'Yes. Entries are prepared and lodged in-house rather than passed '
             'to an outside agent.'),
            ('What happens if cargo is held?',
             'You are told the same day, with the reason and what is needed to '
             'release it.'),
            ('Can you handle a single shipment?',
             'Yes. There is no minimum volume and no retainer.'),
        ],
        'serves': ['Importers and exporters', 'Manufacturers', 'Wholesale and retail',
                   'Agricultural exporters'],
    },
    'construction': {
        'label': 'Construction & building',
        'stock': 'construction', 'template': 'service',
        'palette': 'slate', 'font': 'modern',
        'keywords': ['construction', 'building', 'builder', 'contractor', 'renovation',
                     'civil', 'brickwork', 'roofing', 'concrete', 'site',
                     'extension', 'shopfitting', 'scaffold', 'plastering'],
        'services': [
            ('New builds',
             'From foundation to handover, on a fixed programme.'),
            ('Renovations and extensions',
             'Structural work on occupied buildings, sequenced to keep them usable.'),
            ('Shop and office fit-outs',
             'Partitioning, ceilings, finishes and services, ready to trade.'),
            ('Concrete and structural work',
             'Slabs, footings and retaining, set out and certified.'),
            ('Roofing and waterproofing',
             'Repairs and replacements, with the cause fixed rather than covered.'),
            ('Maintenance contracts',
             'Planned upkeep for portfolios, with one point of contact.'),
        ],
        'why': [
            ('Fixed scope and fixed price',
             'Priced off a drawing and a specification, not an estimate.'),
            ('One site manager throughout',
             'The same person on site from the first week to the last.'),
            ('Programme you can hold us to',
             'Dated milestones, and you are told the week a date moves.'),
            ('Clean, compliant sites',
             'Health and safety files kept current, not assembled at the end.'),
        ],
        'steps': [
            ('Site visit and brief',
             'We measure, photograph and ask what the building has to do.'),
            ('Priced scope of works',
             'Line by line, so you can see what a change costs before you make it.'),
            ('Build to programme',
             'Weekly progress in writing, with photographs.'),
            ('Handover and snag list',
             'Signed off item by item, with certificates and guarantees.'),
        ],
        'faq': [
            ('Do you provide a fixed price?',
             'Yes, once there is a drawing and a specification to price against. '
             'Estimates before that are marked as estimates.'),
            ('How long does a quote take?',
             'Usually two to five working days after the site visit, depending '
             'on the size of the job.'),
            ('Who supervises the site?',
             'A named site manager, reachable directly, for the whole contract.'),
            ('Do you handle plans and approvals?',
             'We work with your professional team, or bring one in if you '
             'do not have one.'),
        ],
        'serves': ['Homeowners', 'Property managers', 'Retail and hospitality',
                   'Commercial landlords'],
    },
    'consulting': {
        'label': 'Advisory & consulting',
        'stock': 'consulting', 'template': 'corporate',
        'palette': 'ocean', 'font': 'modern',
        'keywords': ['consult', 'advisory', 'strategy', 'management',
                     'business improvement', 'b2b', 'corporate',
                     'tender', 'bid', 'process', 'transformation',
                     'operations', 'training'],
        'services': [
            ('Operational reviews',
             'What is actually happening in the business, measured rather than '
             'described.'),
            ('Process design and documentation',
             'The way work should run, written down so it survives staff turnover.'),
            ('Systems selection and implementation',
             'Choosing the tool that fits the process, then getting it in use.'),
            ('Reporting and dashboards',
             'The handful of numbers that tell you whether this month is working.'),
            ('Tender and bid support',
             'Documents assembled, priced and submitted to the deadline.'),
            ('Training and handover',
             'Your team running it without us, which is the point.'),
        ],
        'why': [
            ('Findings you can act on',
             'A short document with decisions in it, not a bound report.'),
            ('Fixed fee per piece of work',
             'Scoped and priced before it starts.'),
            ('We stay until it is in use',
             'A recommendation nobody adopts has not been delivered.'),
            ('Your people keep the knowledge',
             'Everything is documented and handed over.'),
        ],
        'steps': [
            ('A conversation about the problem',
             'An hour is usually enough to know whether we can help.'),
            ('Scoped proposal',
             'What we will look at, what you get, what it costs.'),
            ('The work',
             'Interviews, data, and a draft you see before it is final.'),
            ('Handover',
             'Documented, with the team trained on what changed.'),
        ],
        'faq': [
            ('How do you charge?',
             'A fixed fee for a defined piece of work, agreed before it starts.'),
            ('How long does a review take?',
             'Most run two to six weeks depending on how many sites and systems '
             'are involved.'),
            ('Will this disrupt the business?',
             'Interviews are scheduled around operations and we work from your '
             'existing data wherever possible.'),
            ('What do we get at the end?',
             'A findings document, the process material, and a working handover '
             'to the people who will run it.'),
        ],
        'serves': ['Owner-managed businesses', 'Groups and holdings',
                   'Public sector suppliers', 'Fast-growing SMEs'],
    },
    'software': {
        'label': 'Software & systems',
        'stock': 'software', 'template': 'product',
        'palette': 'plum', 'font': 'technical',
        'keywords': ['software', 'system', 'app', 'application', 'platform', 'saas',
                     'website', 'web', 'portal', 'dashboard', 'integration', 'api',
                     'automation', 'crm', 'erp', 'database', 'mobile'],
        'services': [
            ('Custom systems',
             'Built around how the business runs, not around a template.'),
            ('Integrations',
             'Making the systems you already pay for talk to each other.'),
            ('Automation',
             'The recurring manual work, done by the machine instead.'),
            ('Reporting and dashboards',
             'Live numbers, from the source, without a spreadsheet in between.'),
            ('Websites and portals',
             'Public sites and logged-in areas for staff or customers.'),
            ('Support and maintenance',
             'Someone answerable when it breaks, and updates that keep it safe.'),
        ],
        'why': [
            ('Working software early',
             'You see something running in weeks, not at the end.'),
            ('You own the code',
             'Repository, credentials and documentation are yours.'),
            ('No licence trap',
             'Built on open tooling, hosted where you choose.'),
            ('Priced per phase',
             'Each phase is quoted, delivered and paid before the next begins.'),
        ],
        'steps': [
            ('Scoping session',
             'We walk the current process and write down what it has to do.'),
            ('Phase plan and price',
             'What ships in phase one, and what it costs.'),
            ('Build and review',
             'You use each build and we adjust before moving on.'),
            ('Live, then supported',
             'Deployed, documented, and covered by a support agreement.'),
        ],
        'faq': [
            ('How long until we see something?',
             'A working first version in two to four weeks for most projects.'),
            ('Do we own what you build?',
             'Yes. The code, the credentials and the documentation are handed over.'),
            ('What does support cost?',
             'A monthly agreement based on the size of the system, quoted with '
             'the build.'),
            ('Can you work with our existing systems?',
             'Usually yes, through their APIs or their database. We check that '
             'before quoting.'),
        ],
        'serves': ['Operations teams', 'Finance and admin', 'Field and logistics',
                   'Owner-managers'],
    },
    'creative': {
        'label': 'Design & creative',
        'stock': 'creative', 'template': 'studio',
        'palette': 'mono', 'font': 'classic',
        'keywords': ['design', 'brand', 'branding', 'creative', 'studio', 'agency',
                     'photograph', 'video', 'film', 'content', 'marketing',
                     'social media', 'portfolio', 'graphic', 'identity', 'print'],
        'services': [
            ('Brand identity',
             'A mark, a palette and a type system, with the files to use them.'),
            ('Print and packaging',
             'Artwork prepared to press specification, not to a screen.'),
            ('Photography',
             'Product, premises and people, shot for the way you will use them.'),
            ('Video and motion',
             'Short pieces made for where they will actually be watched.'),
            ('Digital design',
             'Sites and interfaces designed to be built, not just presented.'),
            ('Campaign material',
             'One idea, carried across every format it needs to appear in.'),
        ],
        'why': [
            ('Work made to be used',
             'Delivered as files your printer and your developer can open.'),
            ('One studio, one voice',
             'The same hands across identity, print and digital.'),
            ('Fixed project fees',
             'Scoped up front, with revision rounds stated.'),
            ('You keep the source files',
             'Layered artwork and fonts, handed over at the end.'),
        ],
        'steps': [
            ('Brief',
             'What it is for, who it is for, and what it has to beat.'),
            ('Direction',
             'Two or three routes, presented in context rather than in isolation.'),
            ('Refinement',
             'One route developed, with the revision rounds agreed in advance.'),
            ('Delivery',
             'Final artwork, source files and a short guide to using them.'),
        ],
        'faq': [
            ('How many concepts do we see?',
             'Two or three directions, then one developed. More than that '
             'produces choice, not quality.'),
            ('How many revisions are included?',
             'Stated in the quote, so it is clear before the work starts.'),
            ('Do we get the source files?',
             'Yes, with the fonts licensed to you where licensing allows.'),
            ('Can you work to our existing brand?',
             'Yes. We work inside a brand guide as readily as we write one.'),
        ],
        'serves': ['Founder-led brands', 'Retail and hospitality',
                   'Professional services', 'Manufacturers'],
    },
    'retail': {
        'label': 'Retail & wholesale',
        'stock': 'retail', 'template': 'shop',
        'palette': 'sunset', 'font': 'friendly',
        'keywords': ['shop', 'store', 'retail', 'wholesale', 'stock', 'product',
                     'ecommerce', 'e-commerce', 'online store', 'catalogue',
                     'boutique', 'supplier', 'range', 'trading'],
        'services': [
            ('In-store range',
             'What is on the shelf, and what we can order in for you.'),
            ('Trade and wholesale',
             'Volume pricing for businesses buying to resell or to use.'),
            ('Special orders',
             'Items sourced on request, with a date before you commit.'),
            ('Delivery and collection',
             'Local delivery, or ready for collection the same day.'),
            ('Account customers',
             'Monthly accounts for businesses that buy regularly.'),
            ('Returns and exchanges',
             'Handled over the counter, without a paperwork exercise.'),
        ],
        'why': [
            ('Stock actually on the floor',
             'What we list is what is in the building.'),
            ('Staff who know the range',
             'Advice from people who use what they sell.'),
            ('Trade pricing without a minimum',
             'Better prices for businesses, with no order threshold.'),
            ('Local and reachable',
             'A shop with a door, a phone number and a person behind it.'),
        ],
        'steps': [
            ('Tell us what you need',
             'Phone, email or walk in with the part or the picture.'),
            ('We confirm price and stock',
             'Including a date if it has to be ordered.'),
            ('Collect or have it delivered',
             'Same-day collection, or delivered on our next run.'),
            ('Backed after the sale',
             'Warranty and returns handled here, not sent away.'),
        ],
        'faq': [
            ('Do you deliver?',
             'Yes, locally on scheduled runs, and further by courier at cost.'),
            ('Can we open a trade account?',
             'Yes, on application. Monthly terms once the account is approved.'),
            ('Do you order items in?',
             'Yes, with a confirmed price and date before you commit.'),
            ('What are your hours?',
             'Listed below, and the phone is answered during them.'),
        ],
        'serves': ['Trade and contractors', 'Small businesses', 'Walk-in customers',
                   'Account customers'],
    },
    'food': {
        'label': 'Food & hospitality',
        'stock': 'food', 'template': 'shop',
        'palette': 'sunset', 'font': 'friendly',
        'keywords': ['restaurant', 'cafe', 'coffee', 'kitchen', 'catering', 'menu',
                     'bakery', 'food', 'takeaway', 'bar', 'lodge', 'guest house',
                     'hotel', 'venue', 'chef', 'deli'],
        'services': [
            ('The menu',
             'Cooked to order, changed with what is in season.'),
            ('Functions and private dining',
             'The room, the menu and the staffing, arranged as one booking.'),
            ('Catering off-site',
             'Delivered ready to serve, or cooked and served on site.'),
            ('Takeaway and collection',
             'Ordered ahead and ready when you arrive.'),
            ('Corporate and standing orders',
             'Regular deliveries for offices and sites, invoiced monthly.'),
            ('Dietary requirements',
             'Told in advance, handled properly in the kitchen.'),
        ],
        'why': [
            ('Cooked on the premises',
             'Prepared here, not reheated from a central kitchen.'),
            ('Suppliers we can name',
             'Local where the quality is there, and we will tell you which.'),
            ('Bookings that are honoured',
             'A table held is a table held.'),
            ('One person handles your function',
             'From the first enquiry to the final invoice.'),
        ],
        'steps': [
            ('Enquire',
             'Numbers, date and what the occasion is.'),
            ('Menu and quote',
             'Costed per head, with the extras listed rather than assumed.'),
            ('Confirm',
             'Deposit, final numbers and dietary requirements.'),
            ('On the day',
             'Set up before you arrive, cleared after you leave.'),
        ],
        'faq': [
            ('Do you take bookings?',
             'Yes, by phone or email. Larger tables are worth booking ahead.'),
            ('Can you cater off-site?',
             'Yes, delivered ready to serve or cooked and served on site.'),
            ('Do you handle dietary requirements?',
             'Yes, if we know in advance. The kitchen prepares them separately.'),
            ('Is there a minimum for functions?',
             'It depends on the room and the day. We will tell you when you enquire.'),
        ],
        'serves': ['Walk-in guests', 'Private functions', 'Corporate catering',
                   'Standing orders'],
    },
    'health': {
        'label': 'Health & care',
        'stock': 'health', 'template': 'service',
        'palette': 'forest', 'font': 'modern',
        'keywords': ['clinic', 'medical', 'health', 'doctor', 'dental', 'dentist',
                     'physio', 'therapy', 'practice', 'patient', 'nursing', 'care',
                     'pharmacy', 'wellness', 'psycholog', 'optometr'],
        'services': [
            ('Consultations',
             'Booked appointments with time to actually examine and explain.'),
            ('Assessments and diagnostics',
             'Done here where possible, referred where it is not.'),
            ('Treatment plans',
             'Written down, with the cost and the alternatives.'),
            ('Ongoing care',
             'Scheduled follow-up rather than waiting for a relapse.'),
            ('Referrals',
             'To specialists we know, with the notes sent ahead.'),
            ('Medical aid and accounts',
             'Claims submitted for you where the scheme allows.'),
        ],
        'why': [
            ('Appointments that start on time',
             'Booked properly, so the waiting room is not the treatment.'),
            ('Costs quoted before treatment',
             'Including what the scheme will and will not cover.'),
            ('Continuity of care',
             'You see the same practitioner unless you ask otherwise.'),
            ('Records kept properly',
             'Confidential, current, and available when you are referred.'),
        ],
        'steps': [
            ('Book',
             'By phone or email, with an indication of what it is about.'),
            ('First consultation',
             'History, examination, and what the options are.'),
            ('Agreed plan',
             'Written, costed, and yours to take away.'),
            ('Follow-up',
             'Scheduled, and adjusted as things change.'),
        ],
        'faq': [
            ('Do you take medical aid?',
             'The schemes we submit to are listed below. We will confirm cover '
             'before treatment.'),
            ('How soon can I be seen?',
             'Routine appointments are usually within a few days; urgent cases '
             'are triaged the same day.'),
            ('Will I know the cost first?',
             'Yes. Treatment is quoted before it begins.'),
            ('Do you handle referrals?',
             'Yes, with notes and results sent ahead to the specialist.'),
        ],
        'serves': ['Private patients', 'Medical aid members', 'Employer schemes',
                   'Referred patients'],
    },
    'education': {
        'label': 'Education & training',
        'stock': 'education', 'template': 'service',
        'palette': 'ocean', 'font': 'friendly',
        'keywords': ['school', 'academy', 'college', 'education', 'training',
                     'course', 'learn', 'tutor', 'teach', 'student', 'skills',
                     'workshop', 'seminar', 'accredit', 'curriculum', 'learner'],
        'services': [
            ('Scheduled courses',
             'Published dates, fixed syllabus, a certificate at the end.'),
            ('In-house training',
             'The same material delivered on your premises, to your team.'),
            ('Assessment',
             'Testing against the outcomes, not against attendance.'),
            ('One-to-one tuition',
             'For the gaps a group session cannot close.'),
            ('Learning material',
             'Notes and exercises you keep and can use afterwards.'),
            ('Progress reporting',
             'What was covered, what was achieved, what is next.'),
        ],
        'why': [
            ('Small groups',
             'Numbers capped so questions can actually be asked.'),
            ('Practitioners teaching',
             'Delivered by people who do the work, not only teach it.'),
            ('Material you take away',
             'Yours to keep, and useful after the course ends.'),
            ('Clear outcomes',
             'What you will be able to do, stated before you enrol.'),
        ],
        'steps': [
            ('Enquire',
             'Tell us the level and what you need to be able to do.'),
            ('Placement',
             'A short assessment so nobody sits in the wrong room.'),
            ('The course',
             'Taught, practised and assessed against the outcomes.'),
            ('Certification',
             'Issued on achievement, with a record kept.'),
        ],
        'faq': [
            ('How big are the groups?',
             'Capped, and the cap is stated on each course.'),
            ('Do you train on our premises?',
             'Yes, the same material delivered in-house on agreed dates.'),
            ('Is the training accredited?',
             'Where a course is accredited, the body is named. Where it is not, '
             'we say so.'),
            ('What happens if someone fails?',
             'One reassessment is included; after that it is charged at cost.'),
        ],
        'serves': ['Individual learners', 'Employers', 'Apprentices and interns',
                   'Professional bodies'],
    },
    'trades': {
        'label': 'Trades & maintenance',
        'stock': 'trades', 'template': 'service',
        'palette': 'slate', 'font': 'friendly',
        'keywords': ['plumb', 'electric', 'repair', 'maintenance', 'install',
                     'mechanic', 'workshop', 'weld', 'fabricat', 'aircon', 'hvac',
                     'geyser', 'pump', 'callout', 'call-out', 'handyman', 'garage',
                     'locksmith', 'pest', 'tiling', 'painting'],
        'services': [
            ('Callouts and repairs',
             'Diagnosed and fixed on the first visit wherever parts allow.'),
            ('Installations',
             'Fitted to specification, tested, and left working.'),
            ('Emergencies',
             'The failures that cannot wait for a scheduled slot.'),
            ('Servicing and maintenance',
             'Planned visits that stop the emergency happening.'),
            ('Compliance certificates',
             'Issued where the work requires one.'),
            ('Contract maintenance',
             'For landlords and businesses with more than one property.'),
        ],
        'why': [
            ('Quoted before we start',
             'A price for the job, agreed before a tool comes out.'),
            ('Arrive when we said',
             'A time slot, and a call if we are running late.'),
            ('Parts and labour guaranteed',
             'In writing, for a stated period.'),
            ('Tidy when we leave',
             'The site cleared, not left for you.'),
        ],
        'steps': [
            ('Call or message',
             'Describe the fault, send a photograph if it helps.'),
            ('Slot and price',
             'A time, and either a fixed price or a callout rate stated up front.'),
            ('The work',
             'Fixed on the visit where parts allow, ordered in where they do not.'),
            ('Signed off',
             'Tested with you, invoiced, and guaranteed.'),
        ],
        'faq': [
            ('What does a callout cost?',
             'A stated callout rate, told to you before we come out, and '
             'credited against the repair.'),
            ('How soon can you come?',
             'Same day for emergencies where we can, otherwise within a few '
             'working days.'),
            ('Is the work guaranteed?',
             'Yes, parts and labour, for the period stated on the invoice.'),
            ('Do you issue certificates?',
             'Yes, where the work legally requires one.'),
        ],
        'serves': ['Homeowners', 'Landlords and agents', 'Businesses and sites',
                   'Body corporates'],
    },
    'agriculture': {
        'label': 'Agriculture',
        'stock': 'agriculture', 'template': 'corporate',
        'palette': 'forest', 'font': 'modern',
        'keywords': ['farm', 'agri', 'crop', 'harvest', 'irrigation', 'livestock',
                     'seed', 'fertilis', 'fertiliz', 'orchard', 'vineyard',
                     'packhouse', 'produce', 'grain', 'tractor', 'plantation'],
        'services': [
            ('Production',
             'Grown and harvested to the specification the buyer works to.'),
            ('Packing and grading',
             'Sorted, graded and packed for the market it is going to.'),
            ('Cold chain and storage',
             'Held at temperature from the field to the truck.'),
            ('Supply agreements',
             'Volumes committed for a season, priced up front.'),
            ('Inputs and advisory',
             'What to plant, when, and what it will need.'),
            ('Compliance and traceability',
             'Records that stand up to an audit, per block and per batch.'),
        ],
        'why': [
            ('Traceable to the block',
             'Every batch can be tracked back to where it grew.'),
            ('Consistent grading',
             'The same specification, load after load.'),
            ('Committed volumes',
             'Agreed for the season, so you can plan.'),
            ('Audit-ready records',
             'Kept as we go, not assembled the week before.'),
        ],
        'steps': [
            ('Requirement',
             'Volume, specification and delivery window.'),
            ('Agreement',
             'Price and volume for the season, in writing.'),
            ('Production and packing',
             'Grown, graded and packed to the agreed specification.'),
            ('Delivery',
             'On the window, with the paperwork the buyer needs.'),
        ],
        'faq': [
            ('What volumes can you commit?',
             'Discussed per season and confirmed in writing before planting.'),
            ('Do you pack to buyer specification?',
             'Yes. Grading and packaging are set by the receiving market.'),
            ('Can you supply traceability records?',
             'Yes, per block and per batch, kept as the work happens.'),
            ('Do you handle export documentation?',
             'We work with a clearing agent for export consignments.'),
        ],
        'serves': ['Wholesale markets', 'Retail buyers', 'Exporters', 'Processors'],
    },
    'legal': {
        'label': 'Legal & compliance',
        'stock': 'legal', 'template': 'corporate',
        'palette': 'slate', 'font': 'classic',
        'keywords': ['attorney', 'lawyer', 'legal', 'law', 'litigation', 'conveyanc',
                     'contract', 'compliance', 'notary', 'estate', 'labour law',
                     'commercial law', 'dispute', 'arbitration', 'trust'],
        'services': [
            ('Commercial agreements',
             'Drafted and reviewed so the risk sits where you intended.'),
            ('Dispute resolution',
             'Negotiated first, litigated when it has to be.'),
            ('Property and conveyancing',
             'Transfers handled end to end, with the dates tracked.'),
            ('Labour and employment',
             'Contracts, processes and representation.'),
            ('Corporate and compliance',
             'Structures, resolutions and statutory filings kept current.'),
            ('Estates and trusts',
             'Drafted, administered and wound up.'),
        ],
        'why': [
            ('Fees explained before instruction',
             'Hourly rates or a fixed fee, stated in the mandate.'),
            ('Written in plain language',
             'Advice you can act on without a second opinion to translate it.'),
            ('Matters that move',
             'Progress reported on a schedule, not on request.'),
            ('One attorney on your matter',
             'Not a file passed between desks.'),
        ],
        'steps': [
            ('Initial consultation',
             'The facts, the documents, and whether you have a case.'),
            ('Mandate and fees',
             'Scope and cost, agreed in writing before work begins.'),
            ('The work',
             'Progressed, with you updated on a stated schedule.'),
            ('Conclusion',
             'Outcome, final account, and the file closed properly.'),
        ],
        'faq': [
            ('How are fees calculated?',
             'Either an hourly rate or a fixed fee, set out in the mandate '
             'before work starts.'),
            ('Is the first consultation charged?',
             'Told to you when you book, so there is no surprise.'),
            ('How often will I hear from you?',
             'On an agreed schedule, and immediately when something material '
             'happens.'),
            ('Do you handle matters outside your area?',
             'We refer to a specialist rather than learn on your matter.'),
        ],
        'serves': ['Businesses', 'Individuals', 'Property buyers and sellers',
                   'Employers'],
    },
    'property': {
        'label': 'Property & real estate',
        'stock': 'property', 'template': 'shop',
        'palette': 'slate', 'font': 'classic',
        'keywords': ['property', 'real estate', 'estate agent', 'rental', 'letting',
                     'tenant', 'landlord', 'sectional title', 'body corporate',
                     'managing agent', 'listing', 'valuation', 'residential',
                     'commercial property'],
        'services': [
            ('Sales',
             'Priced on comparable evidence, marketed properly, negotiated for you.'),
            ('Rentals and letting',
             'Tenants screened, leases drawn, deposits held correctly.'),
            ('Property management',
             'Rent collected, maintenance run, statements issued monthly.'),
            ('Valuations',
             'What it is worth now, and what would move it.'),
            ('Body corporate management',
             'Levies, meetings and maintenance for sectional title schemes.'),
            ('Commercial leasing',
             'Space matched to a business, and a lease that fits both sides.'),
        ],
        'why': [
            ('Priced on evidence',
             'Comparable sales, not an optimistic number to win the mandate.'),
            ('Tenants properly screened',
             'Credit, employment and references, checked before a lease.'),
            ('Monthly statements',
             'Where the money went, every month, without asking.'),
            ('One agent on your property',
             'The same person from listing to handover.'),
        ],
        'steps': [
            ('Appraisal',
             'We view it and give you a price with the evidence behind it.'),
            ('Mandate',
             'Term, commission and marketing, agreed in writing.'),
            ('To market',
             'Photographed, listed and shown by appointment.'),
            ('Offer to transfer',
             'Negotiated, and the conveyancing tracked to registration.'),
        ],
        'faq': [
            ('What commission do you charge?',
             'Stated in the mandate before you sign it.'),
            ('How do you screen tenants?',
             'Credit check, employment verification and previous landlord '
             'references before any lease is signed.'),
            ('When are statements issued?',
             'Monthly, with the invoices behind every deduction.'),
            ('Do you manage sectional title schemes?',
             'Yes, including levies, meetings and maintenance.'),
        ],
        'serves': ['Sellers and buyers', 'Landlords', 'Tenants', 'Body corporates'],
    },
    'security': {
        'label': 'Security',
        'stock': 'security', 'template': 'service',
        'palette': 'slate', 'font': 'modern',
        'keywords': ['security', 'guard', 'guarding', 'cctv', 'alarm',
                     'armed response', 'access control', 'surveillance',
                     'patrol', 'monitoring', 'risk assessment',
                     'electric fence'],
        'services': [
            ('Guarding',
             'Static and patrolling officers, posted to a written instruction.'),
            ('Alarm monitoring and response',
             'Signals watched around the clock, with a vehicle dispatched.'),
            ('CCTV and surveillance',
             'Installed where it sees something, monitored or recorded.'),
            ('Access control',
             'Who came in, when, and on whose authority.'),
            ('Risk assessments',
             'The weaknesses found and prioritised before they are exploited.'),
            ('Event and site security',
             'Manned for the duration, with a plan agreed in advance.'),
        ],
        'why': [
            ('Officers you can identify',
             'Named, uniformed, and on a posted roster.'),
            ('Response times stated',
             'Committed to in the contract, and reported against.'),
            ('Incidents reported in writing',
             'Every time, whether or not anything was taken.'),
            ('Equipment maintained',
             'Serviced on a schedule so it works on the night it matters.'),
        ],
        'steps': [
            ('Site assessment',
             'We walk the property and write down where the risk is.'),
            ('Proposal',
             'Manpower, equipment and response, costed.'),
            ('Deployment',
             'Officers posted and equipment commissioned.'),
            ('Reporting',
             'Incidents, patrols and equipment status, on a schedule.'),
        ],
        'faq': [
            ('What is your response time?',
             'Committed in the contract for your area, and reported against '
             'each month.'),
            ('Are your officers registered?',
             'Yes, and registration numbers are available on request.'),
            ('Do you install as well as monitor?',
             'Yes, and we service what we install.'),
            ('Can we start with an assessment only?',
             'Yes. The assessment stands on its own and is yours to act on.'),
        ],
        'serves': ['Residential estates', 'Commercial and industrial sites',
                   'Retail', 'Events'],
    },
    'cleaning': {
        'label': 'Cleaning & hygiene',
        'stock': 'cleaning', 'template': 'service',
        'palette': 'ocean', 'font': 'friendly',
        'keywords': ['clean', 'cleaning', 'hygiene', 'janitorial', 'housekeeping',
                     'laundry', 'sanitis', 'sanitiz', 'washroom', 'carpet',
                     'deep clean', 'pest control', 'waste'],
        'services': [
            ('Daily office cleaning',
             'Same team, same scope, on a written schedule.'),
            ('Deep cleans',
             'Periodic work that the daily round does not cover.'),
            ('Carpet and upholstery',
             'Extracted and dried, not damped down.'),
            ('Washroom hygiene',
             'Consumables, units and servicing on a set frequency.'),
            ('Post-construction and move-out',
             'Handed over ready to occupy.'),
            ('Specialised cleaning',
             'Kitchens, medical rooms and industrial areas, to their standard.'),
        ],
        'why': [
            ('A written scope of work',
             'What gets done, how often, and who checks it.'),
            ('The same team each time',
             'Vetted, trained and known to your staff.'),
            ('Supervised and audited',
             'Spot-checked against the scope, with the results shared.'),
            ('Consumables managed',
             'Stocked before they run out, not after.'),
        ],
        'steps': [
            ('Walk-through',
             'We measure the areas and agree the frequency.'),
            ('Scope and quote',
             'Task by task, with the frequency against each.'),
            ('Service starts',
             'Team introduced, keys and access arranged.'),
            ('Audited monthly',
             'Checked against the scope, with anything short put right.'),
        ],
        'faq': [
            ('Are your staff vetted?',
             'Yes, screened and referenced before placement.'),
            ('Do you work after hours?',
             'Yes. Most office contracts run outside trading hours.'),
            ('Who supplies the consumables?',
             'Either party can; it is priced both ways in the quote.'),
            ('What if the work is not up to standard?',
             'It is corrected at no charge and the audit record shows it.'),
        ],
        'serves': ['Offices', 'Retail and hospitality', 'Industrial sites',
                   'Body corporates'],
    },
    'finance': {
        'label': 'Accounting & finance',
        'stock': 'finance', 'template': 'corporate',
        'palette': 'forest', 'font': 'modern',
        'keywords': ['account', 'accounting', 'bookkeep', 'tax', 'audit', 'payroll',
                     'vat', 'sars', 'financial statement', 'cfo', 'broker',
                     'insurance', 'invest', 'loan', 'finance'],
        'services': [
            ('Bookkeeping',
             'Captured monthly so the numbers are current, not annual.'),
            ('Annual financial statements',
             'Compiled and signed, on a timetable you know in advance.'),
            ('Tax',
             'Returns prepared, submitted and reconciled.'),
            ('Payroll',
             'Run on time, with submissions and payslips handled.'),
            ('VAT and statutory returns',
             'Filed on the due date, with the workings kept.'),
            ('Management accounts',
             'The monthly picture, in time to do something about it.'),
        ],
        'why': [
            ('Deadlines met',
             'Filed on the due date, not the extension.'),
            ('Fixed monthly fee',
             'Quoted on the volume of work, not billed by surprise.'),
            ('Numbers you can read',
             'Explained in a short call, not handed over as a PDF.'),
            ('One accountant on your file',
             'Who knows the business rather than the balance.'),
        ],
        'steps': [
            ('Review',
             'We look at the current books and tell you what state they are in.'),
            ('Engagement letter',
             'Scope, timetable and fee, in writing.'),
            ('Monthly cycle',
             'Captured, reconciled, reported.'),
            ('Year end',
             'Statements, tax and a conversation about what they show.'),
        ],
        'faq': [
            ('What does it cost per month?',
             'A fixed fee based on transaction volume and the number of '
             'submissions, quoted after the review.'),
            ('Can you take over from our current accountant?',
             'Yes. We request the file and reconcile the opening position.'),
            ('Do you handle SARS queries?',
             'Yes, including verification and disputes.'),
            ('How current will our numbers be?',
             'Monthly, with management accounts available within a set number '
             'of working days after month end.'),
        ],
        'serves': ['Owner-managed businesses', 'Sole proprietors', 'Trusts',
                   'Non-profits'],
    },
    'generic': {
        'label': 'Business',
        'stock': 'generic', 'template': 'corporate',
        'palette': 'slate', 'font': 'modern',
        'keywords': [],
        'services': [
            ('What we do',
             'The core of the service, described in the words customers use.'),
            ('How we do it',
             'The way the work runs, so there are no surprises.'),
            ('Who it is for',
             'The customers this suits, and the ones it does not.'),
        ],
        'why': [
            ('Clear pricing',
             'Quoted before the work starts.'),
            ('One point of contact',
             'The same person from the enquiry to the invoice.'),
            ('We do what we said',
             'On the date we said we would do it.'),
        ],
        'steps': [
            ('Get in touch',
             'A call or an email is enough to start.'),
            ('We come back with a plan and a price',
             'In writing, with nothing hidden in it.'),
            ('We get it done',
             'And stay reachable afterwards.'),
        ],
        'faq': [
            ('How do I get a quote?',
             'Send us the details using the form below and we will come back '
             'to you.'),
            ('How quickly do you respond?',
             'Within one working day.'),
        ],
        'serves': [],
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# Reading the reply
# ══════════════════════════════════════════════════════════════════════════════

def detect_industry(*texts):
    """Score the industry packs against everything the client wrote.

    Scored rather than first-match: "we import containers of building material"
    should reach logistics on weight of evidence, not stop at "building".
    """
    blob = ' '.join(t for t in texts if t).lower()
    if not blob.strip():
        return 'generic'
    best, best_score = 'generic', 0
    for key, pack in INDUSTRIES.items():
        score = sum(blob.count(k) * (2 if len(k) > 7 else 1)
                    for k in pack['keywords'])
        if score > best_score:
            best, best_score = key, score
    return best if best_score >= 2 else 'generic'


# What each harvested fact is looked for under. Ordered: the most specific
# phrasing first, so "who will use it" does not answer to "use".
_FIELDS = {
    'goal': ['main goal', 'goal', 'objective', 'trying to achieve', 'achieve',
             'problem', 'why do you want', 'purpose', 'what should it do'],
    'audience': ['audience', 'who will use', 'who is it for', 'customers',
                 'clients', 'target market', 'who visits', 'who are your'],
    'offering': ['services', 'products', 'what do you offer', 'what do you sell',
                 'range', 'what you provide', 'divisions', 'specialit',
                 'specialis', 'what do you do'],
    'pages': ['pages', 'sections', 'features', 'modules', 'functionality',
              'what should the website have', 'must have'],
    'different': ['different', 'better than', 'stand out', 'unique', 'why should',
                  'competitive', 'strength', 'advantage'],
    'coverage': ['areas', 'area', 'coverage', 'region', 'locations', 'branches',
                 'where are you', 'where do you operate', 'suburbs', 'provinces'],
    'hours': ['hours', 'trading times', 'open', 'availability', 'when are you'],
    # Specific phrasings first. "phone" on its own matched "Does it need to
    # work on phones?" and put that whole answer on a Call button.
    'phone': ['contact number', 'telephone number', 'phone number',
              'cell number', 'mobile number', 'whatsapp number', 'landline',
              'telephone', 'contact you on', 'best number'],
    'address': ['address', 'premises', 'physical', 'where are you based',
                'street', 'situated'],
    'email': ['email address', 'contact email', 'e-mail'],
    'launch': ['launch', 'deadline', 'timeline', 'go live', 'when do you need',
               'target date'],
    'budget': ['budget', 'spend', 'price range', 'investment'],
    'likes': ['websites you like', 'sites you like', 'look at', 'reference',
              'inspiration', 'competitors', 'examples'],
    'existing': ['existing website', 'current website', 'current site', 'domain',
                 'do you have a website'],
    'tone': ['tone', 'style', 'feel', 'look and feel', 'brand', 'colours',
             'colors', 'personality'],
    'testimonial': ['testimonial', 'review', 'what do customers say',
                    'reference from a client'],
    'clients': ['clients you work with', 'notable clients', 'who do you work for',
                'accreditation', 'certification', 'memberships', 'awards'],
    'team': ['team', 'staff', 'how many people', 'employees', 'headcount'],
    'years': ['how long have you', 'established', 'founded', 'years in',
              'since when', 'started'],
}


# Cheap sanity checks on the fields that get rendered as data rather than as
# prose. A question sheet is edited per client, so a needle will eventually
# match a question nobody expected it to.
_PLAUSIBLE = {
    'phone': lambda v: len(v) < 40 and len(re.findall(r'\d', v)) >= 7,
    'email': lambda v: len(v) < 80 and '@' in v and ' ' not in v.strip(),
    'hours': lambda v: len(v) < 120,
}


def harvest(req):
    """Everything the answers can be read for, keyed by what it is.

    A question is matched on its wording, so the composer does not depend on a
    particular question sheet having been used - which matters, because the
    sheets are edited per client.
    """
    answers = req.answers or {}
    questions = list(req.questions or [])
    found = {}
    used = set()
    for field, needles in _FIELDS.items():
        for needle in needles:
            for q in questions:
                if q in used:
                    continue
                if needle in q.lower():
                    val = (answers.get(q) or '').strip()
                    if val:
                        found[field] = val
                        used.add(q)
                        break
            if field in found:
                break
    # A value that cannot be what the field claims is worse than a missing one:
    # it gets rendered as a phone number or an email address and published.
    for field, ok in _PLAUSIBLE.items():
        if field in found and not ok(found[field]):
            found.pop(field)

    # Anything left unclaimed is still the client's words and worth keeping:
    # it becomes the "anything else" prose rather than being thrown away.
    extra = [(q, (answers.get(q) or '').strip()) for q in questions
             if q not in used and (answers.get(q) or '').strip()]
    found['_extra'] = extra
    # Every answered pair, in the order they were asked. The copywriter needs
    # all of it, not just the fields this function knew to look for.
    found['_pairs'] = [(q, (answers.get(q) or '').strip()) for q in questions
                       if (answers.get(q) or '').strip()]
    return found


def split_list(text, limit=8):
    """A written answer into list items.

    Clients answer "what do you offer" as a comma list, a newline list, a
    bulleted list or a sentence. The first three split; a sentence is left
    alone rather than chopped at its commas, which is why the length test is
    there.
    """
    text = (text or '').strip()
    if not text:
        return []
    parts = [p.strip(' -•*\t.') for p in re.split(r'[\n;]+|,(?![^(]*\))', text)]
    parts = [p for p in parts if p]
    # A single long clause is prose, not a list.
    if len(parts) < 2 or all(len(p.split()) > 9 for p in parts):
        return []
    cleaned = [tidy_item(p) for p in parts]
    return [p for p in cleaned if len(p) > 1][:limit]


_SENTENCE = re.compile(r'(?<=[.!?])\s+')

# The lead-in a client writes before the thing they actually want. Everything
# up to and including "that"/"to"/"which" is instruction to us, not a headline.
_LEAD_IN = re.compile(
    r'^\s*(?:(?:i|we|they)\s+(?:want|need|would\s+like|are\s+looking\s+for|'
    r'require)|the\s+(?:main\s+)?(?:goal|aim|objective|purpose|idea)\s+is|'
    r'our\s+(?:main\s+)?(?:goal|aim|objective)\s+is|the\s+website\s+should|'
    r'the\s+site\s+should|it\s+should)'
    r'(?:\s+(?:a|an|the|our|my))?'
    r'(?:\s+(?:new\s+)?(?:website|web\s?site|web\s?app|webapp|site|system|'
    r'platform|app|application|portal|page)\w*)?'
    r'\s*(?:that\s+(?:will\s+|can\s+|should\s+)?|which\s+(?:will\s+)?|to\s+|'
    r'for\s+|is\s+to\s+)?',
    re.I)

# A goal stripped of its lead-in often starts with a third-person verb, because
# the subject was the website the client was asking for. The business becomes
# the subject instead.
_NEEDS_SUBJECT = re.compile(
    r'^(lets|allows|helps|gives|shows|makes|enables|provides|delivers|handles|'
    r'tracks|manages|connects|keeps|puts|saves|cuts|brings|takes|turns|lists|'
    r'sells|books|sends|stores|shares)\b', re.I)

# Where a client stops describing the promise and starts explaining the
# present. Everything from here on is reasoning, not a headline.
_TRAILING_CLAUSE = re.compile(
    r'\s+(?:instead of|rather than|as opposed to|because we|because our|'
    r'since we|so that we|so we do not|so we don.t|which we do not|'
    r'which is what we)\b.*$', re.I)


def first_sentence(text, limit=150):
    text = ' '.join((text or '').split())
    if not text:
        return ''
    s = _SENTENCE.split(text)[0].strip()
    if len(s) > limit:
        s = s[:limit].rsplit(' ', 1)[0] + '…'
    return s


def _shorten(text, limit):
    """Shorten a headline at a clause boundary, never with an ellipsis.

    first_sentence() ends an over-long string with an ellipsis, which is right
    for a summary and wrong for a hero: "...one of a thousand accounts at the
    big agents" became "...one of a…". A headline is cut where the sentence
    already breaks, and if there is no break it is cut at a word.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    best = -1
    for mark in (', ', ' who ', ' which ', ' that ', ' so ', ' with ', ' and ',
                 ' for ', ' from ', ' - ', ' – '):
        at = head.rfind(mark)
        # Only a break that leaves a headline worth reading.
        if at > best and at >= 24:
            best = at
    if best > 0:
        return text[:best].rstrip(' ,-–')
    return head.rsplit(' ', 1)[0].rstrip(' ,-–')


def headline(goal, business, industry_label):
    """A headline from the client's stated goal.

    Clients write goals as instructions to us - "we want a website that brings
    in more enquiries" - which is not a headline. The lead-in is stripped and
    what remains is the promise. If nothing usable survives, the business name
    carries the hero and the goal becomes the supporting line, which is always
    better than a mangled sentence.
    """
    text = ' '.join((goal or '').split())
    if not text:
        return business or industry_label
    # Matched as a pattern rather than a list of phrasings: clients write "we
    # want a website that", "we need a web app that", "the goal is to", and a
    # list will always be one phrasing short of the next brief.
    stripped = _LEAD_IN.sub('', text, count=1)
    if stripped and len(stripped.split()) >= 3:
        text = stripped
    trimmed = _TRAILING_CLAUSE.sub('', text)
    if len(trimmed.split()) >= 4:
        text = trimmed
    if business and _NEEDS_SUBJECT.match(text):
        text = f'{business} {text[0].lower()}{text[1:]}'
    text = _SENTENCE.split(' '.join(text.split()))[0].strip().rstrip('.')
    text = _shorten(text, 78)
    if not text or len(text.split()) < 3:
        return business or industry_label
    return text[0].upper() + text[1:]


_NUM = re.compile(
    r'(?:(?P<over>over|more than|about|around|approx\.?|\+)\s*)?'
    r'(?P<num>\d[\d\s,]{0,8}\d|\d)\s*'
    r'(?P<unit>years?|yrs?|clients?|customers?|projects?|jobs?|staff|employees?|'
    r'people|sites?|branches|containers?|vehicles?|trucks?|properties|units?|'
    r'learners?|students?|patients?)', re.I)


def numbers_from(found):
    """Figures the client actually stated, as (value, label) pairs.

    Nothing here is invented. If the answers contain no numbers, the site gets
    no numbers section - an empty one, or worse a plausible one, is how a
    generated site becomes a lie.
    """
    out, seen = [], set()
    for field in ('years', 'team', 'different', 'offering', 'coverage', 'goal',
                  'audience'):
        for m in _NUM.finditer(found.get(field) or ''):
            unit = m.group('unit').lower().rstrip('s')
            if unit in seen:
                continue
            num = re.sub(r'[\s,]', ' ', m.group('num')).strip()
            prefix = '' if not m.group('over') else '+'
            label = {
                'year': 'Years in business', 'yr': 'Years in business',
                'client': 'Clients served', 'customer': 'Customers served',
                'project': 'Projects delivered', 'job': 'Jobs completed',
                'staff': 'People on the team', 'employee': 'People on the team',
                'people': 'People on the team', 'site': 'Sites covered',
                'branche': 'Branches', 'container': 'Containers handled',
                'vehicle': 'Vehicles', 'truck': 'Vehicles',
                'propertie': 'Properties managed', 'unit': 'Units managed',
                'learner': 'Learners trained', 'student': 'Learners trained',
                'patient': 'Patients seen',
            }.get(unit, unit.title())
            out.append((f'{num}{prefix}' if prefix else num, label))
            seen.add(unit)
            if len(out) >= 3:
                return out
    return out

# ══════════════════════════════════════════════════════════════════════════════
# Composing the page
# ══════════════════════════════════════════════════════════════════════════════

_TRAILING = re.compile(
    r'\s*[-–—:]?\s*\b(website|web ?site|site|web page|webpage|project|brief|'
    r'enquiry|questionnaire|question sheet|questions|redesign|rebuild|revamp)\b\s*$',
    re.I)


_LEADING_JOIN = re.compile(
    r'^\s*(?:and|but|or|so|also|plus|as well as|then)\s+', re.I)


def tidy_item(text):
    """A list item lifted out of a sentence, made presentable.

    Clients answer "what do you offer" as one sentence, so the pieces come out
    lowercase and the later ones start with "and". Left alone they publish as
    "and every client gets one contact person", which is the tell of a page
    nobody read before it went live.
    """
    t = ' '.join((text or '').split()).strip(' -\u2022*\t.,;')
    t = _LEADING_JOIN.sub('', t)
    if not t:
        return ''
    # Only the first letter, and only when it is not already a proper noun or
    # an acronym - "eCommerce" and "API" stay as they are.
    if t[0].islower() and not (len(t) > 1 and t[1].isupper()):
        t = t[0].upper() + t[1:]
    return t


def clean_prose(text):
    """A client's answer as copy for a visitor rather than a note to us.

    "We want a website that will bring in more clearing work" is addressed to
    the agency. Stripped of that lead-in it becomes a sentence about the
    business, which is what an about section needs.
    """
    t = ' '.join((text or '').split())
    if not t:
        return ''
    stripped = _LEAD_IN.sub('', t, count=1)
    if stripped and len(stripped.split()) >= 4:
        t = stripped
        t = t[0].upper() + t[1:]
    return t


def business_name(req):
    """The trading name, not the name of the job.

    Requests are titled things like "Riverside Logistics website", and a hero
    that says "Riverside Logistics website" is the giveaway of a generated
    page. The job words are stripped until none are left.
    """
    for candidate in ((req.client_name or '').strip(), (req.title or '').strip()):
        name = candidate
        for _ in range(3):
            trimmed = _TRAILING.sub('', name).strip(' -–—:')
            if trimmed == name:
                break
            name = trimmed
        if len(name) > 1:
            return name
    return (req.client_name or req.title or 'Our business').strip()


def _tokens(text):
    return {w for w in re.findall(r'[a-z]{4,}', (text or '').lower())
            if w not in _STOPWORDS}


_STOPWORDS = {'with', 'from', 'that', 'this', 'your', 'they', 'them', 'have',
              'will', 'been', 'more', 'than', 'into', 'over', 'when', 'what',
              'which', 'their', 'other', 'about', 'after', 'before', 'these',
              'there', 'where', 'while', 'would', 'could', 'should', 'because',
              'services', 'service'}


def describe(name, pack):
    """A description for a service the client named, from the pack.

    The client answers "what do you offer" with bare names - "customs clearing,
    warehousing, road transport". A grid of bare names looks unfinished, so
    each is matched against the pack's own services by word overlap and borrows
    that description. No match means no description, which the renderer handles
    - inventing one for a service we know nothing about is how a generated site
    starts making claims.
    """
    want = _tokens(name)
    if not want:
        return ''
    best, score = '', 0
    for title, body in pack['services']:
        overlap = len(want & _tokens(title)) * 3 + len(want & _tokens(body))
        if overlap > score:
            best, score = body, overlap
    return best if score >= 3 else ''


def _cta_words(industry):
    if industry in ('logistics', 'construction', 'trades', 'cleaning',
                    'security', 'transport'):
        return 'Get a quote', 'Request a quote'
    if industry in ('food', 'retail', 'property'):
        return 'Enquire now', 'Make an enquiry'
    if industry in ('health', 'education'):
        return 'Book an appointment', 'Book now'
    return 'Get in touch', 'Start a conversation'


def tagline_for(pack, found, business):
    """One line for the browser tab and the search result."""
    audience = first_sentence(found.get('audience'), 90)
    coverage = first_sentence(found.get('coverage'), 60)
    # Capped short: this becomes the <title>, the search snippet and the line
    # under the footer logo, and an ellipsis in any of those looks broken.
    if audience:
        return _shorten(f'{pack["label"]} for '
                        f'{audience[0].lower()}{audience[1:]}'.rstrip('.'), 108)
    if coverage:
        return _shorten(f'{pack["label"]} in {coverage}'.rstrip('.'), 108)
    return f'{pack["label"]} — {business}'[:108]


def plan(req, with_copy=True):
    """What kind of site this reply calls for.

    Decided before the site row exists, because the template choice sets the
    palette, the font and the page shape, and those are columns on the row.

    `with_copy` also commissions the model-written copy here rather than in
    compose(), so the tagline it produces can be stored on the row alongside
    the template. It adds a few seconds and needs no key: with no model
    available the packs supply everything.
    """
    found = harvest(req)
    text = ' '.join([req.title or '', getattr(req, 'kind', '') or '']
                    + [v for v in found.values() if isinstance(v, str)]
                    + [f'{q} {a}' for q, a in found.get('_extra', [])])
    industry = detect_industry(text)
    pack = INDUSTRIES[industry]
    business = business_name(req)
    brief = {
        'industry': industry, 'pack': pack, 'found': found,
        'business': business, 'template': pack['template'],
        'palette': pack['palette'], 'font': pack['font'],
        'tagline': tagline_for(pack, found, business),
        'copy': None, 'copy_notes': [],
    }
    if with_copy:
        from . import site_copy
        try:
            brief['copy'] = site_copy.write(business, pack, found,
                                            notes=brief['copy_notes'])
        except Exception:                                        # noqa: BLE001
            # A generated site is worth more than a perfect one. Any failure
            # here leaves the packs in charge.
            import logging
            logging.getLogger(__name__).exception(
                '[site-copy] failed for %s, using the content pack', business)
        written = brief['copy'] or {}
        if written.get('tagline'):
            brief['tagline'] = written['tagline']
        # The model reads the whole brief; the keyword match reads one word at
        # a time. Both values were checked against what the generator has, so
        # anything present here is a real template and a real palette.
        #
        # It may pick a different shape, not a thinner one. Left free, it chose
        # the one-pager for a restaurant with a function room, a changing menu
        # and a testimonial - dropping the gallery and the quote it had been
        # given. Depth is not the model's call to reduce.
        chosen = written.get('layout')
        if chosen:
            from . import site_builder as sb
            if len(sb.layout_for(chosen)) >= len(sb.layout_for(brief['template'])):
                brief['template'] = chosen
        if written.get('palette'):
            brief['palette'] = written['palette']
    return brief


def compose(req, brief=None, images=True):
    """The whole page as an ordered list of (kind, content) pairs.

    Sections are built in the order the chosen template declares, and a section
    with nothing real to say is left out rather than filled - which is why an
    answered brief with three sentences in it still produces a page that reads
    as finished rather than as a form with gaps.
    """
    from . import site_builder as sb
    from . import site_stock as stock

    brief = brief or plan(req)
    pack, found, business = brief['pack'], brief['found'], brief['business']
    industry = brief['industry']
    cta_short, cta_long = _cta_words(industry)
    written = brief.get('copy') or {}

    # Imagery, chosen once so the hero, the about panel and the gallery never
    # show the same photograph twice.
    hero_img = stock.hero(pack['stock']) if images else ''
    # Five: one for the about panel and three for the gallery, which is what
    # fills its row. A two-image gallery in a three-column grid looks short.
    rest = (stock.gallery(pack['stock'], 5, skip=[hero_img] if hero_img else [])
            if images else [])
    about_img = rest[0] if rest else ''
    gallery_imgs = rest[1:] if len(rest) > 1 else []

    offering = split_list(found.get('offering') or found.get('pages'), 6)
    differentiators = split_list(found.get('different'), 4)
    figures = numbers_from(found)
    from_answers, from_pack, from_model = [], [], []

    phone = (found.get('phone') or '').strip()
    email = (found.get('email') or req.client_email or '').strip()

    def build(kind):
        if kind == 'hero':
            points = differentiators[:3] or [t for t, _ in pack['why'][:3]]
            (from_answers if differentiators else from_pack).append('hero ticks')
            heading = headline(found.get('goal'), business, pack['label'])
            if found.get('goal'):
                from_answers.append('headline')
            else:
                from_pack.append('headline')
            sub = (first_sentence(found.get('audience'), 200)
                   or first_sentence(found.get('goal'), 200)
                   or brief['tagline'])
            return {
                'eyebrow': pack['label'],
                'heading': heading,
                'sub': sub,
                'cta_label': cta_short, 'cta_href': '#contact',
                'alt_label': f'Call {phone}' if phone else '',
                'alt_href': f'tel:{phone.replace(" ", "")}' if phone else '',
                'points': points,
                'image': hero_img,
            }

        if kind == 'logos':
            names = split_list(found.get('clients'), 8)
            if not names:
                return None
            from_answers.append('trust strip')
            return {'heading': 'Trusted by', 'items_list': names}

        if kind == 'about':
            body = '\n\n'.join(p for p in (
                clean_prose(found.get('goal', '')),
                clean_prose(found.get('audience', '')),
            ) if p)
            extra = ' '.join(a for _q, a in found.get('_extra', [])[:2])
            if extra and len(body) < 320:
                body = (body + '\n\n' + extra).strip()
            if not body:
                return None
            from_answers.append('about')
            # Not "About us": the heading already says so, and a label that
            # repeats the heading is a wasted line.
            return {'eyebrow': pack['label'], 'heading': f'About {business}',
                    'body': body, 'points': pack['serves'][:4],
                    'image': about_img}

        if kind == 'services':
            if offering:
                items = [{'title': o[:80], 'body': describe(o, pack)}
                         for o in offering]
                from_answers.append('services')
            else:
                items = [{'title': t, 'body': b} for t, b in pack['services']]
                from_pack.append('services')
            return {'eyebrow': 'What we do',
                    'heading': f'What {business} does'
                               if len(business) < 26 else 'What we do',
                    'sub': '', 'items': items}

        if kind == 'stats':
            # Only figures the client stated. An invented number on a client's
            # own website is the one mistake that cannot be walked back.
            if not figures:
                return None
            from_answers.append('numbers')
            return {'heading': '',
                    'items': [{'title': v, 'body': l} for v, l in figures]}

        if kind == 'steps':
            items = [{'title': t, 'body': b} for t, b in pack['steps']]
            if phone or email:
                how = ' or '.join(x for x in (
                    f'call {phone}' if phone else '', f'email {email}' if email else '')
                    if x)
                items[0]['body'] = f'{items[0]["body"]} You can {how}.'
            from_pack.append('how it works')
            return {'eyebrow': 'How it works',
                    'heading': 'Working with us', 'items': items}

        if kind == 'features':
            items = []
            for d in differentiators:
                items.append({'title': d[:80], 'body': describe(d, pack)})
            for t, b in pack['why']:
                if len(items) >= 4:
                    break
                if not any(_tokens(t) & _tokens(i['title']) for i in items):
                    items.append({'title': t, 'body': b})
            (from_answers if differentiators else from_pack).append('why us')
            return {'eyebrow': 'Why us',
                    'heading': f'Why clients stay with {business}'
                               if len(business) < 22 else 'Why clients stay',
                    'sub': '', 'items': items}

        if kind == 'gallery':
            if len(gallery_imgs) < 2:
                return None
            from_pack.append('gallery images')
            # "A look at the work" reads wrong for a restaurant and wrong for
            # a shop. What the pictures are of depends on the trade.
            heading = {
                'food': 'A look inside', 'retail': 'A look inside',
                'health': 'A look inside', 'education': 'A look inside',
                'property': 'A look inside', 'consulting': 'Where we work',
                'creative': 'Selected work', 'software': 'Inside the work',
                'legal': 'Where we work', 'finance': 'Where we work',
            }.get(industry, 'Recent work')
            return {'eyebrow': '', 'heading': heading, 'images': gallery_imgs}

        if kind == 'testimonial':
            quote = (found.get('testimonial') or '').strip()
            if not quote or len(quote) < 20:
                return None
            from_answers.append('testimonial')
            return {'quote': first_sentence(quote, 240) or quote[:240],
                    'name': '', 'role': ''}

        if kind == 'pricing':
            packages = split_list(found.get('budget'), 3)
            if len(packages) < 2:
                return None
            from_answers.append('pricing')
            return {'eyebrow': 'Pricing', 'heading': 'What it costs', 'sub': '',
                    'items': [{'title': p[:60], 'body': ''} for p in packages]}

        if kind == 'faq':
            items = []
            if found.get('coverage'):
                items.append({'title': 'Where do you operate?',
                              'body': found['coverage']})
            if found.get('hours'):
                items.append({'title': 'When are you open?',
                              'body': found['hours']})
            if items:
                from_answers.append('FAQ from answers')
            for q, a in pack['faq']:
                if len(items) >= 6:
                    break
                items.append({'title': q, 'body': a})
            from_pack.append('FAQ')
            return {'eyebrow': 'FAQ', 'heading': 'Questions we get asked',
                    'items': items}

        if kind == 'cta':
            return {'heading': cta_long,
                    'sub': 'Tell us what you need and we will come back to you '
                           'within one working day.',
                    'cta_label': cta_short, 'cta_href': '#contact'}

        if kind == 'contact':
            return {'eyebrow': 'Contact', 'heading': 'Get in touch',
                    'body': 'Send us the details and we will come back to you.',
                    'email': email, 'phone': phone,
                    'address': (found.get('address') or '').strip(),
                    'hours': (found.get('hours') or '').strip()}
        return None

    # The template's shape, plus an FAQ where the pack has one and the layout
    # does not - it is the section that answers the questions a visitor would
    # otherwise phone to ask.
    order = sb.layout_for(brief['template'])
    if 'faq' not in order and pack['faq']:
        order = order[:order.index('cta')] + ['faq'] + order[order.index('cta'):]

    blocks = []
    for kind in order:
        content = build(kind)
        if not content:
            continue
        base = sb.new_block_content(kind)
        base.update(content)
        # The overlay. Only fields that survived vetting are present, so this
        # can never blank something the pack filled - and a field the model
        # got right replaces wording every site of this trade would share.
        overlay = written.get(kind)
        if isinstance(overlay, dict):
            used = {k: v for k, v in overlay.items() if v and not k.startswith('_')}
            if used:
                base.update(used)
                from_model.append(kind)
        blocks.append((kind, base))

    notes = _notes(found, industry, from_answers, from_pack,
                   [u for u in [hero_img, about_img] + gallery_imgs if u],
                   from_model=from_model,
                   copy_notes=brief.get('copy_notes') or [],
                   rejected=(written.get('_rejected') or []))
    return blocks, notes


def _notes(found, industry, from_answers, from_pack, image_urls,
           from_model=(), copy_notes=(), rejected=()):
    """The internal note on the site: commercial detail and what to review.

    Kept off the published page on purpose. Budget and deadlines are between us
    and the client, and whoever reviews the draft needs to know which sections
    are the client's words and which are ours.
    """
    from . import site_stock as stock

    lines = [f'Generated from the client reply. Industry read as: {industry}.']
    commercial = [(k, found.get(k)) for k in ('budget', 'launch', 'likes',
                                              'existing', 'tone')]
    for key, val in commercial:
        if val:
            label = {'budget': 'Budget', 'launch': 'Target launch',
                     'likes': 'Reference sites', 'existing': 'Existing site',
                     'tone': 'Requested tone'}[key]
            lines.append(f'{label}: {val.strip()}')
    if from_answers:
        lines.append('From their answers: ' + ', '.join(dict.fromkeys(from_answers)))
    if from_model:
        lines.append('Written for this client: '
                     + ', '.join(dict.fromkeys(from_model)))
    remaining = [x for x in dict.fromkeys(from_pack) if x not in set(from_model)]
    if remaining:
        lines.append('Standard wording, worth a read: ' + ', '.join(remaining))
    lines.extend(copy_notes)
    if rejected:
        # Named rather than counted: a rejected field usually means the model
        # tried to claim something, and that is worth knowing about a client.
        lines.append('Refused from the copywriter: ' + '; '.join(rejected[:6]))
    credits = stock.credits(image_urls)
    if credits:
        lines.append('Stock images used: ' + '; '.join(credits))
    unanswered = [q for q, a in found.get('_extra', []) if not a]
    if unanswered:
        lines.append(f'{len(unanswered)} question(s) went unanswered.')
    return '\n'.join(lines)
