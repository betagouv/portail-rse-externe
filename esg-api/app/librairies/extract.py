import re
import time as time
import pandas as pd
import fitz


class ExtractTexts:
    def __init__(self, pdf_file_path, num_page_debut=0, num_page_fin=1000) -> None:
        self.pdf_file_path = pdf_file_path
        self.num_page_debut = num_page_debut
        self.num_page_fin = num_page_fin

    # Extraction des textes dans un pdf
    def extract_text_from_pdf(self, pdf_path):
        # Open the PDF file
        document = fitz.open(pdf_path)

        # Initialize a list to hold the extracted text with page numbers
        full_text = []

        # Iterate over each page in the PDF
        for page_num in range(
            self.num_page_debut, min(len(document), self.num_page_fin), 1
        ):
            # Get the page
            page = document.load_page(page_num)

            # Extract text from the page
            page_text = page.get_text(
                option="text", flags=fitz.TEXT_PRESERVE_WHITESPACE
            )

            # Append the text to the full text list with page number
            full_text.append((page_num + 1, page_text))

        return full_text

    def get_paragraphs(self, page_text):
        # Split the text into paragraphs
        paragraphs = page_text.split("\n\n")

        # Remove any empty paragraphs
        paragraphs = [para.strip() for para in paragraphs if para.strip()]
        return paragraphs

    def get_paragraph_per_page(self, extracted_text):
        # Initialize a dictionary to count segment types
        # segment_type_counts = defaultdict(int)

        # For all pages get paragraphs per page
        paragraphs_per_pages = []
        pages_num = []
        for page_num, page_text in extracted_text:
            paragraphs = self.get_paragraphs(page_text)
            paragraphs_per_pages.append(paragraphs)
            pages_num.append(page_num)

        return paragraphs_per_pages, pages_num

    def drop_first_carriage_return_split(self, text):
        parts = text.split("\n")  # Split at every carriage return
        if len(parts) > 1:
            return "\n".join(parts[1:])  # Recombine the parts after the first
        else:
            return "\n"  # Return nothing

    def process_footer(self, paragraphs_per_pages):
        # Find footer in paragraphs (finding the page number)
        digits = []
        for paragraphs in paragraphs_per_pages:
            if len(paragraphs) == 0:
                digits.append(-1)
                continue
            first_part = paragraphs[0].split("\n")[0]
            digit_match = re.search(r"\d+", first_part)
            if digit_match is not None:
                digits.append(int(digit_match.group()))
            else:
                digits.append(-1)
        deduplicated_numbers = sorted(set(digits))
        is_ordered = all(
            deduplicated_numbers[i] <= deduplicated_numbers[i + 1]
            for i in range(len(deduplicated_numbers) - 1)
        )

        # Drop the first part of paragraph if it'a a Footer
        if is_ordered:
            for i, paragraphs in enumerate(paragraphs_per_pages):
                if digits[i] > -1:
                    paragraphs_without_footer = self.drop_first_carriage_return_split(
                        paragraphs[0]
                    )
                    paragraphs_per_pages[i][0] = paragraphs_without_footer

        return paragraphs_per_pages

    def split_into_segments(self, paragraph):
        # Use a regular expression to split the paragraph into sentences
        # This is a simple regex that works for most cases
        segments = re.split(
            r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)(?<!\b\w\w\.)\s", paragraph
        )
        return segments

    def identify_segment_type(self, segment):
        # Check if the segment contains a table by looking for carriage returns
        if "\n" in segment:
            lines = segment.split("\n")
            number_lines = sum(
                1 for line in lines if re.fullmatch(r"\d+", line.strip())
            )

            if number_lines >= 2:
                return "table with numbers"
            else:
                return "table with text only"

        # Check if the segment looks like a title (heuristic: capitalize each word, no ending period, short length)
        words = segment.split()
        if (
            all(word[0].isupper() for word in words)
            and not segment.endswith(".")
            and len(segment) < 50
        ):
            return "title"

        # Check if the segment looks like a sentence (meaningful text with end point)
        if segment.endswith((".", "!", "?")):
            return "sentence"

        # If none of the above, consider it as a sentence
        return "sentence"

    def clean_text(self, segment):
        # Replace unvisible characters different from "\n" by blank
        clean_segment = "".join(
            c if c.isprintable() or c == "\n" else " " for c in segment
        )

        # Replace multiple blanks with a single blank
        clean_segment = re.sub(r" {2,}", " ", clean_segment)

        # Remove special characters except for French
        replacements = {
            "œ": "oe",
            "Œ": "OE",
            "æ": "ae",
            "Æ": "AE",
            "ß": "ss",
            "ø": "o",
            "Ø": "O",
            "đ": "d",
            "Đ": "D",
            "ð": "d",
        }

        # Remplacer les caractères spéciaux par leurs équivalents
        for original, replacement in replacements.items():
            clean_segment = clean_segment.replace(original, replacement)

        # Concaténer les ff fl et fi avec le mot suivant
        pattern = r"(\b\w*(?:fi|fl|ff))\s+(\b\w+\b)"
        clean_segment = re.sub(pattern, r"\1\2", clean_segment)

        # Remplacer les quotes
        # quotes = {"«":'"', "»":'"'}
        # for original, replacement in quotes.items():
        #    clean_segment = clean_segment.replace(original, replacement)

        # Liste des caractères de puces à remplacer par "-"
        bullets = [
            "",
            "➞",
            "→",
            "↓",
            "•",
            "◦",
            "●",
            "▪",
            " n ",
            "▫",
            "►",
            "➢",
            "−",
            "○",
            "◊",
            "♦",
            "▸",
            "▹",
            "‣",
            "❥",
            "✔",
            "✗",
        ]

        # Remplacer les caractères de puces par des tirets
        for bullet in bullets:
            clean_segment = clean_segment.replace(bullet, "-")

        # Process " n" as bullet in some docs
        clean_segment = re.sub(r"(?m)^(\s*)n ", r"\1- ", clean_segment)

        # Process "n\n" as bullet in some docs
        clean_segment = re.sub(r"(?m)^n\n", "- ", clean_segment)

        # Suppression des caractères non désirés tout en conservant les caractères français spéciaux, la ponctuation, et les signes mathématiques
        clean_segment = re.sub(
            r'[^a-zA-Z0-9À-ÿçÇñÑàâäéèêëîïôöùûüÿÿ\'’" ,.;:!?()\[\]\{\}\-\+/%&$€*=^|~π√∫∆∑∏<>≤≥\n\rﬁ]+',
            "",
            clean_segment,
        )

        # Remove spaces before or at the end
        clean_segment = clean_segment.strip()

        return clean_segment

    def exclude_upper_or_space_segments(self, text):
        # Updated regex to include accented uppercase letters and hyphens
        pattern = r"^[A-ZÀ-Ý0-9\s'’,:()%&€*?!.\"//-]*$"
        parts = text.split("\n")  # Split at every carriage return

        # Function to count uppercase letters
        def count_uppercase(s):
            return sum(1 for c in s if c.isupper() or "À" <= c <= "Ý")

        # Filter parts that don't match the pattern and don't have at least 2 uppercases characters
        filtered_parts = [
            part
            for part in parts
            if not (
                re.match(pattern, part) and count_uppercase(part) > 1 and part.strip()
            )
        ]

        # Filter if there is only a number or a number followed by a dot
        filtered_parts = [
            part
            for part in filtered_parts
            if not bool(re.match(r"^\d+\.?$", part.strip()))
        ]

        return "\n".join(filtered_parts)

    def modify_segments(self, text):
        parts = text.split("\n")  # Split at every carriage return

        def modify_part(part):
            if len(part) > 0:
                if part.endswith("*"):
                    part = part + " "

                if part == "-":
                    part = " - "

                if part == " -":
                    part = " - "

                if part == "- ":
                    part = " - "

                if part.startswith("-"):
                    part = " " + part

                if part[0].isupper():
                    part = " " + part

            return part

        modified_parts = [modify_part(part) for part in parts]

        part_modified_join = "\n".join(modified_parts)

        return part_modified_join

    def concatenate_segments_v3(self, segment):
        # Remove lines with only a carriage return
        if len(segment) > 0:
            # Split the text into lines and strip any leading/trailing whitespace
            lines = [line for line in segment.split("\n")]

            # Initialize an empty list to hold the final sentences
            sentences = []
            current_sentence = ""

            for i, line in enumerate(lines):
                # Check if the line starts with a blank followed by an uppercase letter
                # or " - " followed by an uppercase letter
                if (
                    re.match(r"^\s*[A-Z]", line)
                    or re.match(r"^-\s*[A-Z]", line)
                    or line == " - "
                ):
                    if i > 0 and line != " - ":
                        # Check if the previous line ends with a word of more than 3 lowercase characters followed by a space
                        if (
                            re.match(r".*\b[a-z]{1,3}\s$", lines[i - 1])
                            or lines[i - 1] == " - "
                        ):
                            current_sentence += " " + line
                        else:
                            if current_sentence:
                                sentences.append(current_sentence)
                            current_sentence = line

                    else:
                        # If the current sentence is not empty, append it to sentences
                        if current_sentence:
                            sentences.append(current_sentence)
                        current_sentence = line
                else:
                    # Otherwise, continue the current sentence
                    current_sentence += line

            # Add the last sentence if it exists
            if current_sentence:
                sentences.append(current_sentence)

            return sentences

        return []

    def modify_concat_segments(self, concat_segment):
        # Process special characters
        modified_concat_segment = concat_segment.replace("ﬁ n", "fin")

        # Replace sequence of "-" by empty string
        if bool(re.match(r"^[\s-]*$", modified_concat_segment)):
            modified_concat_segment = ""

        # Replace multiple blanks by one
        modified_concat_segment = re.sub(r" {2,}", " ", modified_concat_segment)
        modified_concat_segment = modified_concat_segment.strip()

        return modified_concat_segment

    def extract_segments(self, pages_num, paragraphs_per_pages):
        pd_all_segs = pd.DataFrame([])

        l_page_num = []
        l_paragraph_num = []
        l_segment_num = []
        l_sub_segment_num = []
        l_segment_type = []
        l_segment_text = []

        # Process each page to get paragraphs
        for page_num, paragraphs in zip(pages_num, paragraphs_per_pages):
            # Process each paragraph to get the filtered sentences
            for i, paragraph in enumerate(paragraphs):
                segments = self.split_into_segments(paragraph)

                for j, segment in enumerate(segments):
                    segment_type = self.identify_segment_type(segment)

                    if segment_type in ["table with text only", "sentence"]:
                        if True:  # page_num==246 and i + 1 == 1 and j + 1 == 12 :
                            # print("---------- PARAGRAPH  -------------")
                            # print(paragraph)

                            # print("---------- SEG BRUTE  -------------")
                            # print(segment)

                            # print("---------- CLEAN TEXT  -------------")
                            segment = self.clean_text(segment)
                            # print(segment)

                            # print("---------- EXCLUDE UPPER/SPACES  -------------")
                            segment = self.exclude_upper_or_space_segments(segment)
                            # print(segment)

                            # print("---------- MODIFY SEG  -------------")
                            segment = self.modify_segments(segment)
                            # print(segment)

                            # print("---------- CONCAT TEST  -------------")
                            list_of_segment = self.concatenate_segments_v3(segment)
                            # print("TEST", list_of_segment)

                            # Add sub-segments to
                            for k, sub_segment in enumerate(list_of_segment):
                                sub_segment = self.modify_concat_segments(sub_segment)

                                if len(sub_segment) > 0:
                                    # print(f"Paragraph {page_num}.{i + 1}.{j + 1}.{k + 1} Len: {len(sub_segment)}: {sub_segment} [{segment_type}]")

                                    l_page_num.append(page_num)
                                    l_paragraph_num.append(i + 1)
                                    l_segment_num.append(j + 1)
                                    l_sub_segment_num.append(k + 1)
                                    l_segment_type.append(segment_type)
                                    l_segment_text.append(sub_segment)

                    else:
                        # Save tables of numbers
                        l_page_num.append(page_num)
                        l_paragraph_num.append(i + 1)
                        l_segment_num.append(j + 1)
                        l_sub_segment_num.append(1)
                        l_segment_type.append(segment_type)
                        l_segment_text.append(segment)

        # Get results in Pandas
        pd_all_segs["page_num"] = l_page_num
        pd_all_segs["paragraph_num"] = l_paragraph_num
        pd_all_segs["segment_num"] = l_segment_num
        pd_all_segs["sub_segment_num"] = l_sub_segment_num
        pd_all_segs["segment_type"] = l_segment_type
        pd_all_segs["segment_text"] = l_segment_text

        if len(pd_all_segs) != 0:
            pd_all_segs["segment_len"] = pd_all_segs["segment_text"].str.len()
        else:
            pd_all_segs["segment_len"] = None

        return pd_all_segs

    def process(self):
        # Extract text from the PDF
        extracted_text = self.extract_text_from_pdf(self.pdf_file_path)

        # Extract paragraphs per pages
        paragraphs_per_pages, pages_num = self.get_paragraph_per_page(extracted_text)

        # Remove footer if it exists
        paragraphs_per_pages = self.process_footer(paragraphs_per_pages)

        # Extract segments of texts
        pd_segments = self.extract_segments(pages_num, paragraphs_per_pages)

        return pd_segments
