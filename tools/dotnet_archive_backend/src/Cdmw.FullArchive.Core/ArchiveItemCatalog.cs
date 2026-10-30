using System.Collections.ObjectModel;
using System.Text;
using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveItemCatalog
{
    private readonly IReadOnlyList<ArchiveItemCatalogRecord> _items;
    private readonly IReadOnlyDictionary<int, ArchiveItemCatalogRecord> _byItemId;

    private ArchiveItemCatalog(IReadOnlyList<ArchiveItemCatalogRecord> items)
    {
        _items = items;
        _byItemId = new ReadOnlyDictionary<int, ArchiveItemCatalogRecord>(
            items.GroupBy(static item => item.ItemId)
                .ToDictionary(static group => group.Key, static group => group.First()));
        CategoryFacets = items
            .GroupBy(static item => (item.Category, item.Group), CategoryGroupComparer.Instance)
            .Select(static group => new ItemCatalogCategoryFacet(group.Key.Category, group.Key.Group,
                group.LongCount(), group.LongCount(static item => item.IsDlc)))
            .OrderBy(static facet => facet.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static facet => facet.Group, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public long Count => _items.Count;
    public IReadOnlyList<ArchiveItemCatalogRecord> Items => _items;
    public IReadOnlyList<ItemCatalogCategoryFacet> CategoryFacets { get; }

    public static ArchiveItemCatalog FromRecords(IEnumerable<ArchiveItemCatalogRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var items = records
            .Where(static item => item.ItemId > 0 && !string.IsNullOrWhiteSpace(item.InternalName))
            .Select(Normalize)
            .GroupBy(static item => item.ItemId)
            .Select(static group => group.First())
            .OrderBy(static item => item.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.Group, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.ItemId)
            .ToArray();
        return new ArchiveItemCatalog(items);
    }

    public bool TryGet(int itemId, out ArchiveItemCatalogRecord? item) => _byItemId.TryGetValue(itemId, out item);

    public ArchiveItemCatalogPage Search(
        string? query,
        string? category,
        string? group,
        int pageStart,
        int pageSize,
        bool onlyDlc = false)
    {
        if (pageStart < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(pageStart));
        }
        if (pageSize is < 1 or > 256)
        {
            throw new ArgumentOutOfRangeException(nameof(pageSize), "Finder page size must be between 1 and 256.");
        }

        IEnumerable<ArchiveItemCatalogRecord> matches = _items;
        if (onlyDlc) matches = matches.Where(static item => item.IsDlc);
        if (!string.IsNullOrWhiteSpace(category))
        {
            matches = matches.Where(item => item.Category.Equals(category.Trim(), StringComparison.OrdinalIgnoreCase));
        }
        if (!string.IsNullOrWhiteSpace(group))
        {
            matches = matches.Where(item => item.Group.Equals(group.Trim(), StringComparison.OrdinalIgnoreCase));
        }
        var tokens = NormalizeSearch(query).Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length > 0)
        {
            matches = matches.Where(item => tokens.All(token => item.SearchText.Contains(token, StringComparison.Ordinal)));
        }
        var materialized = matches as IReadOnlyCollection<ArchiveItemCatalogRecord> ?? matches.ToArray();
        return new ArchiveItemCatalogPage(
            materialized.Count,
            materialized.Skip(pageStart).Take(pageSize).ToArray());
    }

    private static ArchiveItemCatalogRecord Normalize(ArchiveItemCatalogRecord source)
    {
        var internalName = source.InternalName.Trim();
        var displayName = string.IsNullOrWhiteSpace(source.DisplayName)
            ? FriendlyName(internalName)
            : source.DisplayName.Trim();
        var localizedNames = Values(source.LocalizedNames);
        var modelStems = Values(source.ModelStems);
        var pacFiles = Values(source.PacFiles);
        var iconPaths = Values(source.IconPaths);
        var (category, group, categoryEvidence) = Classify(
            internalName,
            displayName,
            localizedNames,
            pacFiles,
            modelStems,
            iconPaths,
            source.EquipType);
        var evidence = string.Join(
            "; ",
            new[]
            {
                source.PrefabHashes.Count > 0 ? "prefab link" : "",
                modelStems.Length > 0 ? "model link" : "",
                iconPaths.Length > 0 ? "inventory icon" : "",
                string.IsNullOrWhiteSpace(source.DisplayName) || source.Evidence.Contains("generated friendly name", StringComparison.Ordinal)
                    ? "generated friendly name" : "localized display name",
            }.Where(static value => value.Length > 0));
        return source with
        {
            InternalName = internalName,
            DisplayName = displayName,
            LocalizedNames = localizedNames,
            PrefabHashes = source.PrefabHashes.Distinct().ToArray(),
            ModelStems = modelStems,
            PacFiles = pacFiles,
            IconPaths = iconPaths,
            Category = category,
            Group = group,
            CategoryEvidence = categoryEvidence,
            VariantCount = Math.Max(1, source.VariantCount),
            Evidence = evidence,
            Description = source.Description.Trim(),
            EquipType = source.EquipType.Trim(),
            // The equip slot joins the search text so "helm" finds every helm.
            // The description deliberately does not: it is prose, and folding it
            // in would make one item's flavour text match half the catalogue.
            SearchText = NormalizeSearch(string.Join(
                ' ',
                new[]
                {
                    source.ItemId.ToString(), internalName, displayName, category, group,
                    source.EquipType.Trim(),
                }
                    .Concat(localizedNames)
                    .Concat(pacFiles)
                    .Concat(modelStems)
                    .Concat(iconPaths)
                    )),
        };
    }

    // Definition rules precede multilingual name/model heuristics. Keep in sync
    // with _classify_item_definition in cdmw/core/item_index.py.
    private static (string Category, string Group)? ClassifyDefinition(string internal_name, string equip_type)
    {
        var name = internal_name.ToLowerInvariant();
        var slot = equip_type.ToLowerInvariant();
        // Socket gear can carry an equipment-slot hint without being wearable armor.
        if (name.StartsWith("item_skill_abyssgear_", StringComparison.Ordinal))
            return ("Progression / Reward", "Skill");
        if (name.StartsWith("item_stat_abyssgear_", StringComparison.Ordinal))
            return ("Progression / Reward", "Stat");
        var ship_slots = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["shipsail"] = "Sails",
            ["shipfigurehead"] = "Figureheads",
            ["shipstern"] = "Sterns",
            ["shipcannon"] = "Cannons",
            ["shipbowcannon"] = "Cannons",
            ["turtleshipbowcannon"] = "Cannons",
            ["ghostshipbowcannon"] = "Cannons",
            ["shipteleporter"] = "Teleporters",
        };
        if (ship_slots.ContainsKey(slot))
        {
            return ("Ships", ship_slots[slot]);
        }
        foreach (var (category, group, slots) in new (string, string, string[])[]
        {
            ("Armor", "Head", new[] { "helm" }),
            ("Armor", "Face", new[] { "mask" }),
            ("Armor", "Body", new[] { "upperbody" }),
            ("Armor", "Hands", new[] { "hand", "gauntlet" }),
            ("Armor", "Feet", new[] { "foot" }),
            ("Armor", "Back / Cloak", new[] { "cloak" }),
            ("Accessory", "Ring", new[] { "ring" }),
            ("Accessory", "Earrings", new[] { "earring" }),
            ("Accessory", "Necklace", new[] { "necklace" }),
            ("Accessory", "Belt / Band", new[] { "bracelet" }),
            ("Accessory", "Other Accessory", new[] { "glass" }),
            ("Weapon", "Sword", new[] { "onehandsword", "twohandsword", "twohandgiantsword" }),
            ("Weapon", "Shield", new[] { "onehandshield", "onehandshieldright", "onehandtowershield" }),
            ("Weapon", "Dagger / Rapier", new[] { "onehanddagger", "onehandrapier" }),
            ("Weapon", "Axe / Mace / Hammer", new[] { "onehandaxe", "twohandaxe", "onehandmace", "twohandhammer", "twohandwarhammer" }),
            ("Weapon", "Polearm / Spear", new[] { "twohandspear", "twohandhalberd", "twohandpike" }),
            ("Weapon", "Bow / Crossbow", new[] { "onehandbow", "onehandcrossbow" }),
            ("Weapon", "Firearm", new[] { "onehandcannon", "twohandcannon", "onehandmusket", "onehandpistol", "onehandshotgun", "onehandspeargun", "twohandblowpipe" }),
            ("Weapon", "Fist / Martial", new[] { "onehandfist" }),
            ("Weapon", "Wand / Fan", new[] { "onehandfan", "toolpriestwandbig" }),
            ("Tool", "Backpack / Pack", new[] { "backpack" }),
            ("Tool", "Light / Lantern", new[] { "lantern", "onehandtorch" }),
            ("Tool", "Fishing", new[] { "toolfishingrod" }),
            ("Tool", "Gathering Tool", new[] { "onehanddrill", "onehandsaw", "toolaxe", "toolpickaxe", "toolhoe", "toolsaw", "toolshovel", "toolsythe", "toolhayfork" }),
            ("Mount / Pet", "Mount Gear", new[] { "specialvehiclearmor", "dragonarmor" }),
        })
        {
            if (slots.Contains(slot))
            {
                return (category, group);
            }
        }
        if (slot.StartsWith("horse", StringComparison.Ordinal))
        {
            return ("Mount / Pet", "Horse Gear");
        }
        if (slot.StartsWith("pet", StringComparison.Ordinal))
        {
            return ("Mount / Pet", "Pet Gear");
        }
        if (new[] { "robot", "wagon" }.Any(prefix => slot.StartsWith(prefix, StringComparison.Ordinal)))
        {
            return ("Mount / Pet", "Vehicle Gear");
        }
        if (slot.StartsWith("tool", StringComparison.Ordinal))
        {
            return ("Tool", "Hand Tool");
        }
        if (name.StartsWith("recipe_", StringComparison.Ordinal))
        {
            if ((name.StartsWith("recipe_riding_", StringComparison.Ordinal) && name.Contains("ship")))
            {
                return ("Ships", Regex.IsMatch(name, "_(?:i|ii|iii|iv)$", RegexOptions.CultureInvariant) ? "Blueprint Parts" : "Ship Blueprints");
            }
            if (Regex.IsMatch(name, "^recipe_item_(?:small|big|huge|turtle)?ship_", RegexOptions.CultureInvariant))
            {
                return ("Ships", "Equipment Blueprints");
            }
            return ("Crafting / Recipe", "Recipe Book");
        }
        if ((name.StartsWith("essence_riding_", StringComparison.Ordinal) && name.Contains("ship")))
        {
            return ("Ships", "Ship Materials");
        }
        if (name.StartsWith("trade_", StringComparison.Ordinal))
        {
            return ("Trade Goods", name.EndsWith("_packedinvehicle", StringComparison.Ordinal) ? "Packaged Cargo" : "Trade Goods");
        }
        if (new[] { "item_set_", "dropitem_", "item_abyssgear_recipe_box_" }.Any(prefix => name.StartsWith(prefix, StringComparison.Ordinal)))
        {
            return ("Progression / Reward", "Reward");
        }
        if (name.StartsWith("capsule_riding_", StringComparison.Ordinal))
        {
            return ("Mount / Pet", "Vehicle");
        }
        if (name.StartsWith("enhanced_handcannon_", StringComparison.Ordinal))
        {
            return ("Material", "Upgrade Material");
        }
        if (name.StartsWith("item_skill_", StringComparison.Ordinal))
        {
            return ("Progression / Reward", "Skill");
        }
        if (name.StartsWith("gimmick_cart_", StringComparison.Ordinal))
        {
            return ("Mount / Pet", "Vehicle");
        }
        if (name.StartsWith("visione_chip_", StringComparison.Ordinal))
        {
            return ("Quest / Document", "Memory Fragment");
        }
        if (name.StartsWith("management_reward_", StringComparison.Ordinal))
        {
            return ("Progression / Reward", "Reward");
        }
        if (new[] { "book_", "quest_book_" }.Any(prefix => name.StartsWith(prefix, StringComparison.Ordinal)))
        {
            return ("Quest / Document", "Book / Diary");
        }
        if (new[] { "paper_", "letter_", "noticepaper_", "quest_wantedpaper_", "demeniss_paper_" }.Any(prefix => name.StartsWith(prefix, StringComparison.Ordinal)))
        {
            return ("Quest / Document", "Document");
        }
        if (new[] { "food_", "gimbap_", "abalone_porridge", "parboiled_seafood", "cheese_grilledclams", "grilledclams", "jellyfish_salad", "shortneckclam_noodlesoup", "mussel_soup", "seapineapple_bibimbap", "seastring_seasoned", "seaweed_soup", "item_chocolate_" }.Any(prefix => name.StartsWith(prefix, StringComparison.Ordinal)))
        {
            return ("Consumable", "Food / Drink");
        }
        if (name.StartsWith("item_rare_collect_", StringComparison.Ordinal))
        {
            if (new[] { "coral", "starfish" }.Any(token => name.Contains(token)))
            {
                return ("Material", "Sea Life");
            }
            if (new[] { "abalone", "conch", "mussel", "scallop", "seapineapple", "seaurchin", "sea_", "seacucumber", "seasquirt", "shortneckclam", "penshell" }.Any(token => name.Contains(token)))
            {
                return ("Consumable", "Food / Drink");
            }
        }
        if (new[] { "item_mecoptera", "item_hercules_beetle", "item_eupatorus_beetle", "item_hydrothermal_snail" }.Contains(name))
        {
            return ("Material", name.Contains("snail") ? "Sea Life" : "Insects");
        }
        if (new[] { "malachite", "manganese", "hydrothermalmineral", "item_dropset_collect_manganese" }.Contains(name))
        {
            return ("Material", "Ore / Metal");
        }
        if (new[] { "obsidian", "item_natural_pearl" }.Contains(name))
        {
            return ("Material", "Crystal / Gem");
        }
        if (new[] { "ambergris", "giant_jellyfish_skin" }.Contains(name))
        {
            return ("Material", "Creature Part");
        }
        if (name == "desert_shinystone_01")
        {
            return ("Tool", "Light / Lantern");
        }
        if (name == "item_festival_firework_01")
        {
            return ("Tool", "Throwable / Utility");
        }
        if (name == "destroyed_mechanism")
        {
            return ("Gimmick / Interactive", "Machine Part");
        }
        if (name == "snakerelic_0001")
        {
            return ("Item", "Relic");
        }
        var housing = (new[] { "item_in_", "item_me_00_str_", "background_", "backgroundcd_", "collection_", "tent_", "item_tent_", "wood_tower_", "hellhound_wood_tower_", "gimmick_tower_", "gimmick_spot_wolfrider_watchtower_", "gimmick_tent_", "flag_graymane_", "item_lamp_", "lamp_", "troll_lamp_", "troll_academy_stand_lamp_", "item_straw_", "item_background_", "item_festival_", "item_cd_", "item_basecamp_", "item_carpenter_", "item_animal_feedstock_", "item_marnigolem_scarecrow_", "item_farm_fan_", "item_mantlet_", "item_barricade_", "item_product_prop_", "item_kusunsla_", "item_switch_firebellows_", "item_troll_academy_torchlight_", "item_gimmick_box_", "item_gimmick_breakable_", "item_gimmick_in_", "item_gimmick_craft_", "item_gimmick_graymane_wood_totem_", "item_gimmick_jail_", "item_gimmick_management_", "item_gimmick_lamp_", "item_gimmick_tool_windmill_", "item_gimmick_tower_", "item_gimmick_wood_bench_", "item_gimmick_island_warehouse_", "item_gimmick_tool_scarecrow_", "item_gimmick_tool_dryingstand_", "item_gimmick_tool_automata_", "item_gimmick_toilet_" }.Any(prefix => name.StartsWith(prefix, StringComparison.Ordinal)) || name.Contains("_housing"));
        if (housing)
        {
            if (new[] { "tent", "shade", "stable", "gazebo", "cliff", "attachbuilding", "sawmill_000", "tower", "windmill" }.Any(token => name.Contains(token)))
            {
                return ("Housing / Prop", "Buildings / Tents");
            }
            if (new[] { "door", "window", "fence", "gate", "barricade", "mantlet" }.Any(token => name.Contains(token)))
            {
                return ("Housing / Prop", "Doors / Windows / Fences");
            }
            if (new[] { "bookcase", "cabinet", "closet", "chair", "table", "bed", "shelf", "bench", "desk", "carpenter" }.Any(token => name.Contains(token)))
            {
                return ("Housing / Prop", "Furniture");
            }
            if (new[] { "chest", "box", "barrel", "crate", "storage", "farm_attach_" }.Any(token => name.Contains(token)))
            {
                return ("Housing / Prop", "Container");
            }
            return ("Housing / Prop", "Decor");
        }
        return null;
    }

    private static (string Category, string Group, string Evidence) Classify(
        string internalName,
        string displayName,
        IReadOnlyList<string> localizedNames,
        IReadOnlyList<string> pacFiles,
        IReadOnlyList<string> modelStems,
        IReadOnlyList<string> iconPaths,
        string equipType)
    {
        if (ClassifyDefinition(internalName, equipType) is { } definition)
            return (definition.Category, definition.Group, "Recovered item definition / equip type");
        var primaryNames = new[] { internalName, displayName }.Concat(localizedNames).ToArray();
        var primaryText = string.Join(' ', primaryNames).ToLowerInvariant();
        var relationText = string.Join(' ', pacFiles.Concat(modelStems).Concat(iconPaths)).ToLowerInvariant();
        var text = $"{primaryText} {relationText}";
        var compactInternalName = CompactText(internalName);
        const string evidence = "Recovered item/model naming";

        if (CatalogTextMatchesAny(primaryText, "oblivion of the past", "artisan's hand", "artisans hand"))
            return ("Weapon", "Axe / Mace / Hammer", evidence);
        if (CatalogTextMatchesAny(primaryText, "broken visione")) return ("Armor", "Head", evidence);
        if (compactInternalName.Contains("horsearmor", StringComparison.Ordinal)) return ("Mount / Pet", "Horse Gear", evidence);
        if (primaryNames.Any(static name => Regex.IsMatch(
                name ?? string.Empty,
                @"(?:^|[^a-z0-9])barding\s*$",
                RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)))
        {
            return ("Mount / Pet", "Horse Gear", evidence);
        }
        if (CatalogTextMatchesAny(primaryText, "glove", "gloves")) return ("Armor", "Hands", evidence);
        if (CatalogTextMatchesAny(primaryText, "boot", "boots")) return ("Armor", "Feet", evidence);
        if (CatalogTextMatchesAny(primaryText, "lantern")) return ("Tool", "Light / Lantern", evidence);

        foreach (var (group, tokens) in new (string, string[])[]
        {
            ("Key / Permit", ["homekey", "visitorpass", "license", "permit", "permission", " key ", " pass "]),
            ("Clue / Report", ["sighting", "news", "report", "record", "clue", "evidence"]),
            ("Book / Diary", ["diary", "journal", "epistle"]),
            ("Document", ["letter", "note", "contract", "memo", "notepad", "noticepaper", "notice paper", "blueprint", "manual", "document", "scroll", "paper"]),
        })
        {
            if (CatalogTextMatchesAny(primaryText, tokens) || CatalogTextMatchesAny(relationText, tokens))
            {
                return ("Quest / Document", group, evidence);
            }
        }
        var compactPrimary = CompactText(primaryText);
        if (compactPrimary.Contains("lostletter", StringComparison.Ordinal)
            || (compactPrimary.Contains("letter", StringComparison.Ordinal)
                && compactPrimary.EndsWith("letter", StringComparison.Ordinal)))
        {
            return ("Quest / Document", "Document", evidence);
        }
        if (CatalogTextMatchesAny(primaryText, "recipe", "craftingrecipe", "crafting recipe"))
            return ("Crafting / Recipe", "Recipe Book", evidence);
        if (CatalogTextMatchesAny(text, "itemcatch_fishingrod", "fishingrod", "fishing rod"))
            return ("Tool", "Fishing", evidence);
        if (CatalogTextMatchesAny(
                text,
                "petarmor", "pet armor", "catarmor", "cat armor", "dogarmor", "dog armor", "puppy",
                "cat outfit", "dog outfit", "pet outfit", "cat hat", "dog hat", "pet hat", "cat helm", "dog helm", "pet helm"))
        {
            return ("Mount / Pet", "Pet Gear", evidence);
        }
        if (CatalogTextMatchesAny(primaryText, "potion", "medicine", "elixir", "tonic", "remedy", "recovery"))
            return ("Consumable", "Potion / Medicine", evidence);
        if (CatalogTextMatchesAny(primaryText, "food", "drink", "meal", "bread", "meat", "fruit", "carrot", "pear"))
            return ("Consumable", "Food / Drink", evidence);
        if (CatalogTextMatchesAny(primaryText, "onehandspear", "twohandspear", "onehandlance", "lance", "spear", "halberd", "alebard", "pike", "scythe"))
            return ("Weapon", "Polearm / Spear", evidence);

        foreach (var rule in new (string Category, string Group, string[] Tokens)[]
        {
            ("Armor", "Head", ["helmet", "helm", "_hel", "hood", "hat", "cap", "crown", "circlet", "headdress"]),
            ("Armor", "Face", ["face", "mask", "veil"]),
            ("Armor", "Back / Cloak", ["cloak", "cape", "mantle", "shawl"]),
            ("Armor", "Body", ["armor", "armour", "plate", "_ub", "body", "cuirass", "coat", "jacket", "vest", "shirt", "tunic", "robe", "dress", "gown", "mail", "hauberk", "jerkin", "chest", "costume", "outfit", "uniform"]),
            ("Armor", "Hands", ["glove", "gloves", "hand", "gauntlet", "gauntlets", "bracer", "bracers", "vambrace", "wrist", "sleeve"]),
            ("Armor", "Legs", ["pants", "trouser", "trousers", "skirt", "leg", "legs", "_lb"]),
            ("Armor", "Feet", ["boot", "boots", "foot", "feet", "shoe", "shoes", "sandal", "sabaton", "greave", "greaves", "_sho"]),
            ("Tool", "Backpack / Pack", ["backpack", "back pack", "back_pack", "thrusterpack", "pack", "satchel", "pouch"]),
        })
        {
            if (CatalogTextMatchesAny(primaryText, rule.Tokens)) return (rule.Category, rule.Group, evidence);
        }

        foreach (var rule in new (string Category, string Group, string[] Tokens)[]
        {
            ("Weapon", "Sword", ["onehandsword", "twohandsword", "twohandgiantbastard", "bastard", "sword", "01_sword", "02_sword"]),
            ("Weapon", "Shield", ["shield", "03_shield"]),
            ("Weapon", "Dagger / Rapier", ["onehanddagger", "dagger", "rapier"]),
            ("Weapon", "Axe / Mace / Hammer", ["onehandaxe", "twohandaxe", "twohandgiantaxe", "onehandmace", "twohandmace", "warhammer", "warhamme", "axe", "mace", "hammer"]),
            ("Weapon", "Polearm / Spear", ["onehandspear", "twohandspear", "onehandlance", "lance", "spear", "halberd", "alebard", "pike", "scythe"]),
            ("Weapon", "Bow / Crossbow", ["onehandbow", "twohandbow", "bow", "crossbow"]),
            ("Weapon", "Firearm", ["pistol", "musket", "shotgun", "cannon", "flamethrower", "icethrower", "lightningthrower", "thrower", "magicbullet", "gatling", "laser"]),
            ("Weapon", "Fist / Martial", ["fist", "knuckle"]),
            ("Weapon", "Wand / Fan", ["priestwand", "wand", "wingfan"]),
            ("Weapon", "Other Weapon", ["weapon"]),
            ("Armor", "Head", ["helmet", "helm", "_hel", "head", "hood", "hat", "cap", "crown", "circlet", "headdress"]),
            ("Armor", "Face", ["face", "mask", "veil"]),
            ("Armor", "Back / Cloak", ["cloak", "cape", "mantle", "shawl", "back"]),
            ("Armor", "Body", ["armor", "plate", "_ub", "body", "cuirass", "coat", "jacket", "vest", "shirt", "tunic", "robe", "dress", "gown", "mail", "hauberk", "jerkin", "chest"]),
            ("Armor", "Hands", ["glove", "gloves", "hand", "gauntlet", "gauntlets", "bracer", "bracers", "vambrace", "wrist", "sleeve"]),
            ("Armor", "Legs", ["pants", "trouser", "trousers", "skirt", "leg", "legs", "_lb"]),
            ("Armor", "Feet", ["boot", "boots", "foot", "feet", "shoe", "shoes", "sandal", "sabaton", "greave", "greaves", "_sho"]),
            ("Armor", "Other Armor", ["costume", "outfit", "uniform"]),
            ("Accessory", "Earrings", ["earring", "earrings"]),
            ("Accessory", "Necklace", ["necklace", "testneck", "neck"]),
            ("Accessory", "Ring", ["ring"]),
            ("Accessory", "Amulet / Charm", ["amulet", "charm", "talisman", "pendant", "necklace", "neck"]),
            ("Accessory", "Belt / Band", ["belt", "band"]),
            ("Accessory", "Other Accessory", ["accessory", "jewelry", "jewel", "glasses", "eyewear"]),
            ("Mount / Pet", "Horse Gear", ["horsegear", "horse gear", "horse", "saddle", "stirrup", "bridle", "mount", "riding"]),
            ("Mount / Pet", "Pet Gear", ["petgear", "pet gear", "companionpet"]),
            ("Mount / Pet", "Vehicle", ["vehicle"]),
            ("Consumable", "Potion / Medicine", ["potion", "medicine", "elixir", "tonic", "remedy", "recovery"]),
            ("Consumable", "Food / Drink", ["food", "drink", "meal", "bread", "meat", "fruit", "carrot", "pear"]),
            ("Consumable", "Other Consumable", ["consumable"]),
            ("Crafting / Recipe", "Recipe Book", ["recipe", "craftingrecipe", "crafting recipe"]),
            ("Crafting / Recipe", "Crafting", ["craft", "crafting"]),
            ("Tool", "Backpack / Pack", ["backpack", "back_pack", "thrusterpack", "pack"]),
            ("Tool", "Gathering Tool", ["pickaxe", "axe_tool", "gathering", "mining", "lumbering", "drill", "chainsaw", "hoe", "sickle", "trirake", "woodrake", "repairtool"]),
            ("Tool", "Light / Lantern", ["lantern", "torch"]),
            ("Tool", "Fishing", ["fishing", "rod"]),
            ("Tool", "Throwable / Utility", ["bomb", "installationbomb", "bola", "dart"]),
            ("Tool", "Hand Tool", ["broom", "rake", "saw", "stick", "abacus", "pen", "drum", "trumpet", "chain"]),
            ("Tool", "Other Tool", ["tool"]),
            ("Material", "Ore / Metal", ["ore", "ingot", "metal"]),
            ("Material", "Cloth / Leather", ["cloth", "leather", "fabric"]),
            ("Material", "Wood / Stone", ["wood", "stone", "branch"]),
            ("Material", "Creature Part", ["horn", "tooth", "claw", "scale"]),
            ("Material", "Crystal / Gem", ["crystal", "gem"]),
            ("Material", "Other Material", ["material"]),
            ("Character Customization", "Hair", ["charactercustomize", "hair", "defulthair", "defaulthair", "tiehair"]),
            ("Character Customization", "Body / Appearance", ["aging", "deaging", "scar", "customize"]),
            ("Gimmick / Interactive", "Gimmick", ["gimmick", "circusmachine"]),
            ("Gimmick / Interactive", "Machine Part", ["machine", "core", "tank", "fusion"]),
            ("Housing / Prop", "Furniture", ["furniture", "bookcase", "cabinet", "closet", "chair", "table", "bed", "shelf"]),
            ("Housing / Prop", "Decor", ["flowerpot", "pot", "lamp", "picture", "painting", "trophy", "ornament", "doll", "bell", "thurible", "sphere", "globe", "pillar"]),
            ("Housing / Prop", "Collection Prop", ["collection_prop", "collection prop", "housing"]),
            ("Housing / Prop", "Container", ["chest", "box", "barrel", "crate"]),
            ("Quest / Document", "Quest", ["quest"]),
            ("Quest / Document", "Key / Permit", ["key", "homekey", "permit", "pass", "visitorpass", "license", "permission"]),
            ("Quest / Document", "Book / Diary", ["book", "diary", "journal", "epistle"]),
            ("Quest / Document", "Map / Treasure", ["map", "treasure", "treasuremap"]),
            ("Quest / Document", "Clue / Report", ["clue", "report", "record", "log", "evidence", "degree"]),
            ("Quest / Document", "Flag / Marker", ["flag", "marker", "picket"]),
            ("Quest / Document", "Document", ["document", "scroll", "letter", "paper", "bundle", "blueprint", "memo", "notepad", "manual"]),
            ("Quest / Document", "Token / Seal", ["token", "seal"]),
            ("Progression / Reward", "Skill", ["skill"]),
            ("Progression / Reward", "Stat", ["stat", "attack", "defense", "resistance", "critical"]),
            ("Progression / Reward", "Artifact", ["artifact"]),
            ("Progression / Reward", "Reward", ["reward", "bounty", "income", "contribution"]),
            ("Progression / Reward", "Currency", ["money", "gold", "golden", "golden999k", "coin"]),
        })
        {
            if (CatalogTextMatchesAny(text, rule.Tokens)) return (rule.Category, rule.Group, evidence);
        }
        return ("Item", "Unclassified", "No stronger category evidence was recovered");
    }

    private static bool CatalogTextMatchesAny(string text, params string[] tokens)
    {
        var rawText = (text ?? string.Empty).ToLowerInvariant();
        var normalizedText = NormalizeCatalogText(rawText);
        var compactText = CompactText(rawText);
        foreach (var rawToken in tokens)
        {
            var token = (rawToken ?? string.Empty).Trim().ToLowerInvariant();
            if (token.Length == 0) continue;
            if (token.Contains('_') || token.StartsWith('_') || token.EndsWith('_'))
            {
                if (rawText.Contains(token, StringComparison.Ordinal)) return true;
                continue;
            }
            var normalizedToken = NormalizeCatalogText(token).Trim();
            if (normalizedToken.Length > 0
                && normalizedText.Contains($" {normalizedToken} ", StringComparison.Ordinal))
            {
                return true;
            }
            var compactToken = CompactText(token);
            if (compactToken.Length >= 7 && compactText.Contains(compactToken, StringComparison.Ordinal)) return true;
        }
        return false;
    }

    private static string CompactText(string value)
    {
        var builder = new StringBuilder(value.Length);
        foreach (var character in value)
        {
            if (character is >= 'a' and <= 'z' or >= 'A' and <= 'Z' or >= '0' and <= '9')
            {
                builder.Append(char.ToLowerInvariant(character));
            }
        }
        return builder.ToString();
    }

    private static string NormalizeCatalogText(string value)
    {
        var builder = new StringBuilder(value.Length + 2);
        builder.Append(' ');
        var priorWasSpace = true;
        foreach (var character in value)
        {
            if (char.IsLetterOrDigit(character))
            {
                builder.Append(char.ToLowerInvariant(character));
                priorWasSpace = false;
            }
            else if (!priorWasSpace)
            {
                builder.Append(' ');
                priorWasSpace = true;
            }
        }
        if (!priorWasSpace) builder.Append(' ');
        return builder.ToString();
    }

    private static string FriendlyName(string value)
    {
        value = System.Text.RegularExpressions.Regex.Replace(value, "(?<=[a-z])(?=[A-Z])", " ");
        var builder = new StringBuilder(value.Length);
        var previousWasSeparator = true;
        foreach (var character in value)
        {
            if (character is '_' or '-' or '.')
            {
                if (!previousWasSeparator) builder.Append(' ');
                previousWasSeparator = true;
                continue;
            }
            builder.Append(previousWasSeparator ? char.ToUpperInvariant(character) : character);
            previousWasSeparator = false;
        }
        return builder.ToString().Trim();
    }

    private static string[] Values(IEnumerable<string>? values) => (values ?? [])
        .Where(static value => !string.IsNullOrWhiteSpace(value))
        .Select(static value => value.Trim())
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .ToArray();

    private static string NormalizeSearch(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return string.Empty;
        var builder = new StringBuilder(value.Length);
        var separator = false;
        foreach (var character in value.Normalize().ToLowerInvariant())
        {
            if (char.IsLetterOrDigit(character))
            {
                if (separator && builder.Length > 0) builder.Append(' ');
                builder.Append(character);
                separator = false;
            }
            else
            {
                separator = true;
            }
        }
        return builder.ToString();
    }

    private sealed class CategoryGroupComparer : IEqualityComparer<(string Category, string Group)>
    {
        public static CategoryGroupComparer Instance { get; } = new();

        public bool Equals((string Category, string Group) left, (string Category, string Group) right) =>
            left.Category.Equals(right.Category, StringComparison.OrdinalIgnoreCase)
            && left.Group.Equals(right.Group, StringComparison.OrdinalIgnoreCase);

        public int GetHashCode((string Category, string Group) value) => HashCode.Combine(
            StringComparer.OrdinalIgnoreCase.GetHashCode(value.Category),
            StringComparer.OrdinalIgnoreCase.GetHashCode(value.Group));
    }
}

public sealed record ArchiveItemCatalogRecord(
    int ItemId,
    string InternalName,
    string DisplayName,
    IReadOnlyList<string> LocalizedNames,
    IReadOnlyList<uint> PrefabHashes,
    IReadOnlyList<string> ModelStems,
    IReadOnlyList<string> PacFiles,
    IReadOnlyList<string> IconPaths,
    string Category = "",
    string Group = "",
    string CategoryEvidence = "",
    int VariantCount = 1,
    string Evidence = "",
    string SearchText = "",
    string Description = "",
    string EquipType = "",
    bool IsDlc = false);

public sealed record ArchiveItemCatalogPage(long TotalMatches, IReadOnlyList<ArchiveItemCatalogRecord> Items);
