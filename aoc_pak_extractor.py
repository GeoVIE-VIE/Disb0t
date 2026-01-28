#!/usr/bin/env python3
"""
Ashes of Creation PAK File Recipe Extractor

This script extracts crafting recipe data from AoC's Unreal Engine 5 PAK files
and compiles it into a JSON database for use with the Discord bot.

Requirements:
    pip install ue4parse pycryptodome

Usage:
    1. Set GAME_PATH to your Ashes of Creation installation directory
    2. Run: python aoc_pak_extractor.py
    3. Output will be saved to aoc_recipes.json

Note: You may need to find the AES encryption key for the PAK files.
      Check online resources or use AES key finder tools.
"""

import os
import sys
import json
import re
import struct
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

# Path to Ashes of Creation installation
# Common paths:
#   Steam: C:\Program Files (x86)\Steam\steamapps\common\Ashes of Creation\
#   Standalone: C:\Program Files\Intrepid Studios\Ashes of Creation\
GAME_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Ashes of Creation"

# AES-256 encryption key (hex string, 64 characters)
# You'll need to find this - it changes with game updates
# Use tools like AES Key Finder on the game executable
AES_KEY = None  # Set to None if PAKs are unencrypted, or "0x..." if encrypted

# Output file
OUTPUT_FILE = "aoc_recipes.json"

# ============== PAK PARSING ==============

class PakReader:
    """Simple PAK file reader for Unreal Engine 5"""

    PAK_MAGIC = 0x5A6F12E1

    def __init__(self, pak_path: str, aes_key: Optional[str] = None):
        self.pak_path = Path(pak_path)
        self.aes_key = self._parse_aes_key(aes_key) if aes_key else None
        self.entries: Dict[str, dict] = {}

    def _parse_aes_key(self, key_str: str) -> bytes:
        """Parse AES key from hex string"""
        if key_str.startswith('0x'):
            key_str = key_str[2:]
        return bytes.fromhex(key_str)

    def _decrypt_block(self, data: bytes) -> bytes:
        """Decrypt a block of data using AES-256"""
        if not self.aes_key:
            return data
        try:
            from Crypto.Cipher import AES
            cipher = AES.new(self.aes_key, AES.MODE_ECB)
            return cipher.decrypt(data)
        except ImportError:
            logger.error("pycryptodome not installed. Run: pip install pycryptodome")
            raise

    def read_index(self) -> bool:
        """Read the PAK file index to get list of files"""
        try:
            with open(self.pak_path, 'rb') as f:
                # Read footer (last 221 bytes for UE5)
                f.seek(-221, 2)
                footer = f.read(221)

                # Check magic number
                magic = struct.unpack('<I', footer[-4:])[0]
                if magic != self.PAK_MAGIC:
                    # Try older format
                    f.seek(-44, 2)
                    footer = f.read(44)
                    magic = struct.unpack('<I', footer[-4:])[0]
                    if magic != self.PAK_MAGIC:
                        logger.warning(f"Invalid PAK magic in {self.pak_path}")
                        return False

                logger.info(f"Successfully opened PAK: {self.pak_path.name}")
                return True

        except Exception as e:
            logger.error(f"Error reading PAK {self.pak_path}: {e}")
            return False


class UAssetParser:
    """Parser for Unreal Engine .uasset files"""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.names: List[str] = []
        self.imports: List[dict] = []
        self.exports: List[dict] = []

    def read_int32(self) -> int:
        val = struct.unpack('<i', self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return val

    def read_uint32(self) -> int:
        val = struct.unpack('<I', self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return val

    def read_int64(self) -> int:
        val = struct.unpack('<q', self.data[self.pos:self.pos+8])[0]
        self.pos += 8
        return val

    def read_fstring(self) -> str:
        length = self.read_int32()
        if length == 0:
            return ""
        if length < 0:
            # Unicode string
            length = -length * 2
            s = self.data[self.pos:self.pos+length-2].decode('utf-16-le')
            self.pos += length
        else:
            s = self.data[self.pos:self.pos+length-1].decode('utf-8', errors='replace')
            self.pos += length
        return s

    def parse_header(self) -> bool:
        """Parse the uasset header"""
        try:
            # Check magic
            magic = self.read_uint32()
            if magic != 0x9E2A83C1:
                return False

            # Skip version info
            self.pos = 0x1A  # Jump to name count

            return True
        except:
            return False


class RecipeExtractor:
    """Extract recipe data from Unreal Engine assets"""

    # Common patterns for recipe-related assets
    RECIPE_PATTERNS = [
        r'.*Recipe.*',
        r'.*Crafting.*',
        r'.*DT_.*Recipe.*',  # DataTable recipes
        r'.*BP_Recipe.*',    # Blueprint recipes
        r'.*Ingredient.*',
    ]

    def __init__(self, game_path: str, aes_key: Optional[str] = None):
        self.game_path = Path(game_path)
        self.aes_key = aes_key
        self.recipes: Dict[str, dict] = {}
        self.items: Dict[str, dict] = {}

    def find_pak_files(self) -> List[Path]:
        """Find all PAK files in the game directory"""
        pak_dir = self.game_path / "AshesOfCreation" / "Content" / "Paks"
        if not pak_dir.exists():
            # Try alternate paths
            alt_paths = [
                self.game_path / "Content" / "Paks",
                self.game_path / "Paks",
            ]
            for alt in alt_paths:
                if alt.exists():
                    pak_dir = alt
                    break
            else:
                logger.error(f"Could not find Paks directory in {self.game_path}")
                return []

        paks = list(pak_dir.glob("*.pak"))
        logger.info(f"Found {len(paks)} PAK files")
        return paks

    def extract_from_fmodel_export(self, export_dir: str) -> None:
        """
        Parse recipe data from FModel JSON exports.

        This is the RECOMMENDED approach:
        1. Download FModel from https://fmodel.app/
        2. Open the AoC PAK files in FModel
        3. Export all DataTables as JSON
        4. Point this script to the export directory
        """
        export_path = Path(export_dir)
        if not export_path.exists():
            logger.error(f"Export directory not found: {export_dir}")
            return

        # Find all JSON files
        json_files = list(export_path.rglob("*.json"))
        logger.info(f"Found {len(json_files)} JSON files to parse")

        for json_file in json_files:
            try:
                self._parse_json_export(json_file)
            except Exception as e:
                logger.debug(f"Could not parse {json_file}: {e}")

    def _parse_json_export(self, json_path: Path) -> None:
        """Parse a single FModel JSON export for recipe data"""
        with open(json_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return

        # Check if this looks like recipe data
        file_name = json_path.stem.lower()

        # Look for DataTable exports with recipe data
        if isinstance(data, list):
            for entry in data:
                self._extract_recipe_from_entry(entry, file_name)
        elif isinstance(data, dict):
            self._extract_recipe_from_entry(data, file_name)

    def _extract_recipe_from_entry(self, entry: dict, source: str) -> None:
        """Extract recipe information from a parsed entry"""
        if not isinstance(entry, dict):
            return

        # Look for recipe-like structures
        # Common UE5 recipe patterns:

        # Pattern 1: Direct recipe with ingredients array
        if 'Ingredients' in entry or 'ingredients' in entry:
            ingredients = entry.get('Ingredients') or entry.get('ingredients', [])
            output = entry.get('Output') or entry.get('output') or entry.get('ResultItem')

            if output and ingredients:
                recipe_name = self._get_item_name(output)
                if recipe_name:
                    self.recipes[recipe_name] = {
                        'name': recipe_name,
                        'output': self._parse_output(output),
                        'ingredients': self._parse_ingredients(ingredients),
                        'profession': entry.get('Profession') or entry.get('profession', ''),
                        'level': entry.get('Level') or entry.get('level', 0),
                        'source': source
                    }

        # Pattern 2: Row-based DataTable
        if 'Rows' in entry:
            for row_name, row_data in entry.get('Rows', {}).items():
                self._extract_recipe_from_entry(row_data, f"{source}/{row_name}")

        # Pattern 3: Nested properties
        for key in ['Properties', 'properties', 'Data', 'data']:
            if key in entry:
                self._extract_recipe_from_entry(entry[key], source)

    def _get_item_name(self, item_ref: Any) -> Optional[str]:
        """Extract item name from various reference formats"""
        if isinstance(item_ref, str):
            # Extract name from path like "/Game/Items/Weapons/Sword.Sword"
            match = re.search(r'([^/\.]+)(?:\.[^\.]+)?$', item_ref)
            return match.group(1) if match else item_ref
        elif isinstance(item_ref, dict):
            return (item_ref.get('ItemName') or
                    item_ref.get('itemName') or
                    item_ref.get('Name') or
                    item_ref.get('name') or
                    item_ref.get('DisplayName') or
                    item_ref.get('RowName'))
        return None

    def _parse_output(self, output: Any) -> dict:
        """Parse recipe output item"""
        if isinstance(output, str):
            return {'name': self._get_item_name(output), 'quantity': 1}
        elif isinstance(output, dict):
            return {
                'name': self._get_item_name(output),
                'quantity': output.get('Quantity') or output.get('quantity') or output.get('Count') or 1
            }
        return {'name': str(output), 'quantity': 1}

    def _parse_ingredients(self, ingredients: Any) -> List[dict]:
        """Parse recipe ingredients list"""
        result = []

        if not isinstance(ingredients, list):
            ingredients = [ingredients]

        for ing in ingredients:
            if isinstance(ing, dict):
                name = self._get_item_name(ing)
                qty = ing.get('Quantity') or ing.get('quantity') or ing.get('Count') or ing.get('Amount') or 1
                if name:
                    result.append({'name': name, 'quantity': int(qty)})
            elif isinstance(ing, str):
                result.append({'name': self._get_item_name(ing), 'quantity': 1})

        return result

    def save_database(self, output_path: str) -> None:
        """Save extracted data to JSON file"""
        output = {
            'version': '1.0',
            'extracted_date': datetime.now().isoformat(),
            'game_path': str(self.game_path),
            'recipe_count': len(self.recipes),
            'recipes': self.recipes
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(self.recipes)} recipes to {output_path}")


def print_instructions():
    """Print detailed usage instructions"""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║           Ashes of Creation Recipe Extractor - Setup Instructions            ║
╚══════════════════════════════════════════════════════════════════════════════╝

This script extracts crafting recipe data from AoC game files.

RECOMMENDED METHOD (Using FModel):
─────────────────────────────────
1. Download FModel from: https://fmodel.app/

2. Configure FModel:
   • Set Game Directory to your AoC installation
   • If prompted for AES key, you may need to find it online or use
     a key finder tool on the game executable

3. In FModel:
   • Navigate to the Content folder
   • Look for DataTables related to crafting/recipes:
     - DT_Recipes_*
     - DT_CraftingRecipes_*
     - DT_Items_* (for item data)
   • Right-click → Export → Save as JSON

4. Run this script with the export path:
   python aoc_pak_extractor.py --fmodel-export "C:/path/to/fmodel/exports"

ALTERNATE METHOD (Direct PAK parsing):
─────────────────────────────────────
1. Find your AoC installation path
2. Update GAME_PATH in this script
3. If PAKs are encrypted, find the AES key and set AES_KEY
4. Run: python aoc_pak_extractor.py

FINDING THE AES KEY:
───────────────────
• Check: https://github.com/Cracko298/UE4-AES-Key-Extracting-Guide
• Use tools like AES Key Finder on the game's .exe
• Search AOC modding communities/Discord servers

OUTPUT:
──────
The script creates aoc_recipes.json with structure:
{
  "recipes": {
    "Iron Sword": {
      "name": "Iron Sword",
      "output": {"name": "Iron Sword", "quantity": 1},
      "ingredients": [
        {"name": "Iron Ingot", "quantity": 5},
        {"name": "Leather Strips", "quantity": 2}
      ],
      "profession": "Weaponsmithing",
      "level": 10
    }
  }
}
""")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Extract crafting recipes from Ashes of Creation game files'
    )
    parser.add_argument(
        '--fmodel-export', '-f',
        help='Path to FModel JSON export directory (recommended method)'
    )
    parser.add_argument(
        '--game-path', '-g',
        default=GAME_PATH,
        help='Path to AoC installation directory'
    )
    parser.add_argument(
        '--aes-key', '-k',
        default=AES_KEY,
        help='AES-256 encryption key (hex string)'
    )
    parser.add_argument(
        '--output', '-o',
        default=OUTPUT_FILE,
        help='Output JSON file path'
    )
    parser.add_argument(
        '--instructions', '-i',
        action='store_true',
        help='Show detailed setup instructions'
    )

    args = parser.parse_args()

    if args.instructions:
        print_instructions()
        return

    extractor = RecipeExtractor(args.game_path, args.aes_key)

    if args.fmodel_export:
        # Parse FModel exports (recommended)
        logger.info(f"Parsing FModel exports from: {args.fmodel_export}")
        extractor.extract_from_fmodel_export(args.fmodel_export)
    else:
        # Direct PAK parsing
        print_instructions()
        logger.info("\nAttempting direct PAK parsing...")

        pak_files = extractor.find_pak_files()
        if not pak_files:
            logger.error("No PAK files found. Please check your game path.")
            logger.info(f"Looking in: {args.game_path}")
            return

        for pak in pak_files:
            reader = PakReader(str(pak), args.aes_key)
            reader.read_index()

    # Save results
    if extractor.recipes:
        extractor.save_database(args.output)
        logger.info(f"\nSuccess! Extracted {len(extractor.recipes)} recipes.")
        logger.info(f"Output saved to: {args.output}")
    else:
        logger.warning("\nNo recipes found. Try using FModel to export DataTables as JSON first.")
        logger.info("Run with --instructions for detailed setup guide.")


if __name__ == '__main__':
    main()
