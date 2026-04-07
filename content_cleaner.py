import re


# boilerplate patterns commonly found on dark web forums and sites
# these get stripped before AI analysis to improve classification quality
BOILERPLATE_PATTERNS = [
    # forum chrome / navigation
    re.compile(r'⚠️.*?⚠️', re.DOTALL),
    re.compile(r'Your JavaScript is Disabled.*?alternative browser\s*\.?', re.DOTALL | re.IGNORECASE),
    re.compile(r'Install the app\s*Install', re.IGNORECASE),
    re.compile(r'(?:Log\s*in|Sign\s*in)\s*(?:Register|Sign\s*up)', re.IGNORECASE),
    re.compile(r'Menu\s+(?:Log\s*in|Home|Forums)', re.IGNORECASE),
    re.compile(r'You are using an out of date browser.*?alternative browser\s*\.?', re.DOTALL | re.IGNORECASE),
    re.compile(r'(?:Enable|Please enable) (?:JavaScript|cookies).*?(?:features|properly)\s*\.?', re.DOTALL | re.IGNORECASE),
    re.compile(r'This site uses cookies.*?(?:accept|agree|OK)\s*\.?', re.DOTALL | re.IGNORECASE),

    # common forum footers
    re.compile(r'(?:Powered by|Running on)\s+(?:XenForo|phpBB|vBulletin|MyBB|SMF|Discourse).*', re.IGNORECASE),
    re.compile(r'©\s*\d{4}.*?(?:All rights reserved|Terms|Privacy).*', re.IGNORECASE),
    re.compile(r'(?:Terms of Service|Privacy Policy|DMCA|Contact Us)\s*[\|·•]\s*', re.IGNORECASE),

    # navigation elements
    re.compile(r'(?:Home|Forums|Members|What\'s new|New posts|Search|Latest activity)\s*(?:Forums|Members|What\'s new|New posts|Search|Latest activity)*', re.IGNORECASE),
    re.compile(r'(?:First|Prev|Next|Last)\s*(?:Page)?\s*\d+\s*of\s*\d+', re.IGNORECASE),
    re.compile(r'Page \d+ of \d+', re.IGNORECASE),

    # share/social buttons
    re.compile(r'(?:Share|Tweet|Pin|Like|Follow)\s*(?:on\s+)?(?:Facebook|Twitter|Reddit|Telegram|WhatsApp)', re.IGNORECASE),

    # captcha / verification
    re.compile(r'(?:Please )?(?:verify|prove) (?:you are|that you\'re) (?:human|not a (?:robot|bot)).*', re.IGNORECASE),

    # empty / placeholder
    re.compile(r'^\s*(?:Loading|Please wait|Redirecting)\.{0,3}\s*$', re.IGNORECASE | re.MULTILINE),
]

# unicode/emoji noise commonly used as decoration
DECORATIVE_PATTERNS = re.compile(r'[⭐️✨🔥💀🎯🔒🛡️⚡️🌐🔗💰💎🚀]{2,}')

# repeated whitespace
MULTI_NEWLINE = re.compile(r'\n{3,}')
MULTI_SPACE = re.compile(r'[ \t]{3,}')


def clean_content(text: str) -> str:
    """
    strip boilerplate from scraped dark web page content.
    returns cleaned text with actual page content preserved.
    """
    if not text or text.startswith("[ERROR"):
        return text

    cleaned = text

    # strip boilerplate patterns
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = pattern.sub('', cleaned)

    # reduce decorative emoji clusters to single instance
    cleaned = DECORATIVE_PATTERNS.sub('', cleaned)

    # normalize whitespace
    cleaned = MULTI_NEWLINE.sub('\n\n', cleaned)
    cleaned = MULTI_SPACE.sub(' ', cleaned)
    cleaned = cleaned.strip()

    # if cleaning removed everything, return original (better than empty)
    if len(cleaned) < 20:
        return text

    return cleaned


def extract_meaningful_section(text: str, max_chars: int = 1500) -> str:
    """
    extract the most meaningful section from cleaned content.
    skips short navigation-like lines at the start and finds
    the first substantive block of text.
    """
    if not text or len(text) <= max_chars:
        return text

    lines = text.split('\n')
    meaningful_start = 0

    # skip leading short lines (likely navigation/breadcrumbs)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) > 60 and not stripped.startswith(('Home', 'Forums', 'Menu', '⭐')):
            meaningful_start = i
            break

    # reconstruct from meaningful start
    meaningful_text = '\n'.join(lines[meaningful_start:])

    if len(meaningful_text) > max_chars:
        meaningful_text = meaningful_text[:max_chars]

    return meaningful_text.strip()
