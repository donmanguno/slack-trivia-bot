import re
import logging
logger = logging.getLogger(__name__)


def html_to_markdown(text: str) -> str:
		logger.debug(f"html_to_markdown: input: {text}...")
		text = strip_extraneous_html(text)
		text = replace_html_with_mrkdwn(text)
		logger.debug(f"html_to_markdown: output: {text}")
		return text

def strip_extraneous_html(text: str) -> str:
		text = re.sub(r'<p.*?>', "", text)
		text = re.sub(r'</p.*?>', "", text)
		text = re.sub(r'<div.*?>', "", text)
		text = re.sub(r'</div.*?>', "", text)
		text = re.sub(r'<span.*?>', "", text)
		text = re.sub(r'</span.*?>', "", text)
		text = text.replace("<u>", "")
		text = text.replace("</u>", "")
		return text

def replace_html_with_mrkdwn(text: str) -> str:
		text = text.replace("&nbsp;", " ")
		text = re.sub(r'<br( ?/)?>', "\n", text)
		text = re.sub(r'<strong>(.*?)</strong>', r'*\1*', text)
		text = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'*\1*', text)
		text = re.sub(r'<i>(.*?)</i>', r'_\1_', text)
		text = re.sub(r'<s>(.*?)</s>', r'~\1~', text)
		text = re.sub(r'~\s*([ \t\_\*]*)\s*~', r'\1', text) # remove consecutive pairs of ~
		text = re.sub(r'\*([ \t\_\~]*)\*', r'\1', text) # remove consecutive pairs of *
		text = re.sub(r'_\s*([ \t\*\~]*)\s*_', r'\1', text) # remove consecutive pairs of _
		text = re.sub(r'<img .*?src=\"(.*?)\".*?>', r'<\1|>', text)
		text = re.sub(r'<a .*?href=\"(.*?)\".*?>(.*?)</a>', r'<\1|\2>', text)
		text = re.sub(r'(?<![<|])(https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&\/\/=;]*))', r'<\1|>', text)
		text = re.sub(r'<customemoji .*?alt=\"(.*?)\".*?><\/customemoji>', r':\1:', text)

		text = replace_blockquote(text)
		text = replace_code_block(text)
		text = re.sub(r'<code>(.*?)</code>', r'`\1`', text) # replace non-codeblock code tags with just the code
		text = replace_lists(text)
		text = replace_table(text)

		return text.strip()

def replace_lists(text: str) -> str:
		def process_list_content(content, list_type, nesting_levels: dict[str, int]):
				result_lines = []
				i = 0

				while i < len(content):
						# Look for <li> tags
						li_start = content.find('<li>', i)
						if li_start == -1:
								break

						# Find matching </li>
						li_end, li_content = find_matching_tag(content, li_start, 'li')
						if not li_end or not li_content: break

						# Check if this li contains nested lists
						nested_ul_start = li_content.find('<ul>')
						nested_ol_start = li_content.find('<ol>')

						# Process text before any nested list
						first_nested = None
						text_before_nested = li_content
						if nested_ul_start != -1 or nested_ol_start != -1:
								first_nested = min(
										nested_ul_start if nested_ul_start != -1 else len(li_content),
										nested_ol_start if nested_ol_start != -1 else len(li_content)
								)
								text_before_nested = li_content[:first_nested]

						# Get the marker for this list item
						marker = get_marker(list_type, nesting_levels, len(result_lines))  # item index

						# Calculate indentation (one tab per nesting level)
						indent = '\t' * (nesting_levels["ul"] + nesting_levels["ol"])

						# Process nested lists recursively
						nested_content = li_content[first_nested:] if first_nested and first_nested < len(li_content) else ""
						processed_nested = ""

						if nested_ul_start != -1 or nested_ol_start != -1:
								# Process nested lists in the remaining content
								processed_nested = process_list_content(
										nested_content,
										'ul' if nested_ul_start != -1 else 'ol',
										{ "ul": nesting_levels["ul"] + 1, "ol": nesting_levels["ol"] } if list_type == 'ul' else { "ul": nesting_levels["ul"], "ol": nesting_levels["ol"] + 1 }
								)

						# Combine text and nested content
						item_text = text_before_nested.strip()
						if processed_nested:
								item_text += "\n" + processed_nested

						# Add the formatted line
						result_lines.append(f"{indent}{marker} {item_text}")

						i = li_end  # Move past </li>

				return "\n".join(result_lines)

		def get_marker(list_type, nesting_levels: dict[str, int], item_index):
				"""
				Determine the appropriate marker based on context.
				"""
				if list_type == 'ul':
						if nesting_levels["ul"]%3 == 0:
								return '•'
						elif nesting_levels["ul"]%3 == 1:
								return '◦'
						else:  # nesting_level%3 == 2
								return '▪︎'

				else:  # list_type == 'ol'
						if nesting_levels["ol"]%3 == 0:
								return str(item_index + 1) + '.'
						elif nesting_levels["ol"]%3 == 1:
								return chr(ord('a') + item_index) + '.'
						else:  # nesting_level%3 == 2
								roman_numerals = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx"]
								if item_index < len(roman_numerals):
										return roman_numerals[item_index] + '.'
								else:
										return str(item_index + 1) + '.'

		# Main processing: find all list tags and process them
		result = text
		i = 0

		while i < len(result):
				# don't do this in code blocks
				if result[i:i+3] == '```':
						close_code_block_pos = result.find('```', i + 3)
						if close_code_block_pos != -1:
								i = close_code_block_pos + 3
								continue
				if result[i:i+1] == '`':
						close_code_block_pos = result.find('`', i + 1)
						if close_code_block_pos != -1:
								i = close_code_block_pos + 1
								continue

				ul_pos = result.find('<ul>', i)
				ol_pos = result.find('<ol>', i)

				if ul_pos == -1 and ol_pos == -1:
						break

				# Find the first list tag
				if ol_pos == -1 or (ul_pos != -1 and ul_pos < ol_pos):
						list_type = 'ul'
						start_pos = ul_pos
				else:
						list_type = 'ol'
						start_pos = ol_pos

				# Find matching closing tag
				end_pos, content = find_matching_tag(result, start_pos, list_type)
				if not end_pos or not content: break

				# Process the list content
				processed = process_list_content(content, list_type, {"ul": 0, "ol": 0})

				# Replace the original HTML with processed markdown
				result = result[:start_pos] + processed + result[end_pos:]

				# Continue from after the replacement
				i = start_pos + len(processed)

		return result

def find_matching_tag(text: str, start_pos: int, open_tag: str) -> tuple[int, str] | tuple[None, None]:
		stack = []
		i = start_pos
		tag_name = open_tag  # 'ul' or 'ol'

		while i < len(text):
				if text[i:i+len(f'<{tag_name}>')] == f'<{tag_name}>':
						stack.append(i)
						i += len(f'<{tag_name}>')
				elif text[i:i+len(f'</{tag_name}>')] == f'</{tag_name}>':
						stack.pop()
						if len(stack) == 0:
								# Found matching closing tag
								content_start = start_pos + len(f'<{tag_name}>')
								return (i + len(f'</{tag_name}>'), text[content_start:i])
						else: i += 1
				else:
						i += 1
		return None, None

def replace_blockquote(text: str) -> str:
		pattern = r'<blockquote>(.*?)</blockquote>'
		matches = list(re.finditer(pattern, text, re.DOTALL))
		for match in matches:
				lines = match.group(1).split("\n")
				lines = ["> " + line for line in lines if line.strip()]
				lines = "\n".join(lines)
				text = text.replace(match.group(0), lines)
		return text

def replace_code_block(text: str) -> str:
		pattern = r'<codeblock.*?>(?:<code.*?>)?(.*?)(?:</code>)?</codeblock>'
		matches = list(re.finditer(pattern, text, re.DOTALL))
		for match in matches:
				code = match.group(1)
				text = text.replace(match.group(0), f"```{code}\n```")
		return text

def replace_table(text: str) -> str:
		pattern = r'<table>(.*?)</table>'
		matches = list(re.finditer(pattern, text, re.DOTALL))
		for match in matches:
				table_html = match.group(0).replace("\n", "")
				soup = BeautifulSoup(table_html, "html.parser")
				buf = StringIO()
				writer = csv.writer(buf)
				for tr in soup.find_all("tr"):
						cells = [cell.get_text() for cell in tr.find_all(["td", "th"])]
						writer.writerow(cells)
				csv_table = buf.getvalue()
				text = text.replace(match.group(0), f'```{csv_table}```')

		return text