using System.Collections.ObjectModel;
using System.Text;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveItemCatalog
{
    private static readonly Regex DisplayVariantSuffix = new(
        @"(?:\s*\(\+\d+\)|\s+\+\d+)$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly Regex InternalVariantSuffix = new(
        @"(?:_?\+\d+|_lv\d+|_level\d+|_grade\d+)$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex ModelVariantSuffix = new(
        @"(?:_(?:index\d+(?:_[lr])?|sub\d+)|_[lrustcd])$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex ModelTrailingLetterVariant = new(
        @"(?<=\d)[a-z]$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private readonly IReadOnlyList<ArchiveItemCatalogRecord> _items;
    private readonly IReadOnlyDictionary<int, ArchiveItemCatalogRecord> _byItemId;
    private readonly IReadOnlyList<ItemCatalogCategoryFacet> _categoryFacets;
    private readonly IReadOnlyList<ItemCatalogValueFacet> _materialFacets;

    private ArchiveItemCatalog(IReadOnlyList<ArchiveItemCatalogRecord> items)
    {
        _items = items;
        _byItemId = new ReadOnlyDictionary<int, ArchiveItemCatalogRecord>(
            items.GroupBy(static item => item.ItemId)
                .ToDictionary(static group => group.Key, static group => group.First()));
        _categoryFacets = items
            .GroupBy(static item => (item.Category, item.Group), CategoryGroupComparer.Instance)
            .Select(static group => new ItemCatalogCategoryFacet(group.Key.Category, group.Key.Group, group.LongCount()))
            .OrderBy(static facet => facet.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static facet => facet.Group, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        _materialFacets = items
            .SelectMany(static item => item.MaterialTags)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .GroupBy(static value => value, StringComparer.OrdinalIgnoreCase)
            .Select(static group => new ItemCatalogValueFacet(group.Key, group.LongCount()))
            .OrderByDescending(static facet => facet.Count)
            .ThenBy(static facet => facet.Value, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public long Count => _items.Count;
    public IReadOnlyList<ArchiveItemCatalogRecord> Items => _items;
    public IReadOnlyList<ItemCatalogCategoryFacet> CategoryFacets => _categoryFacets;
    public IReadOnlyList<ItemCatalogValueFacet> MaterialFacets => _materialFacets;

    public static ArchiveItemCatalog FromRecords(IEnumerable<ArchiveItemCatalogRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var normalized = records
            .Where(static item => item.ItemId > 0 && !string.IsNullOrWhiteSpace(item.InternalName))
            .Select(NormalizeRecord)
            .GroupBy(BuildGroupKey, StringComparer.OrdinalIgnoreCase)
            .Select(MergeVariants)
            .OrderBy(static item => item.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.Group, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.InternalName, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return new ArchiveItemCatalog(normalized);
    }

    public bool TryGet(int itemId, out ArchiveItemCatalogRecord? item) =>
        _byItemId.TryGetValue(itemId, out item);

    public ArchiveItemCatalogPage Search(
        string? query,
        string? category,
        string? group,
        string? materialTag,
        int pageStart,
        int pageSize)
    {
        if (pageStart < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(pageStart));
        }
        if (pageSize is < 1 or > 200)
        {
            throw new ArgumentOutOfRangeException(nameof(pageSize), "Item Finder page size must be between 1 and 200.");
        }

        var queryTokens = Tokenize(query);
        IEnumerable<ArchiveItemCatalogRecord> matches = _items;
        if (!string.IsNullOrWhiteSpace(category))
        {
            matches = matches.Where(item => item.Category.Equals(category.Trim(), StringComparison.OrdinalIgnoreCase));
        }
        if (!string.IsNullOrWhiteSpace(group))
        {
            matches = matches.Where(item => item.Group.Equals(group.Trim(), StringComparison.OrdinalIgnoreCase));
        }
        if (!string.IsNullOrWhiteSpace(materialTag))
        {
            matches = matches.Where(item => item.MaterialTags.Contains(materialTag.Trim(), StringComparer.OrdinalIgnoreCase));
        }
        if (queryTokens.Length > 0)
        {
            matches = matches.Where(item => queryTokens.All(token => item.SearchText.Contains(token, StringComparison.Ordinal)));
        }

        var materialized = matches as IReadOnlyCollection<ArchiveItemCatalogRecord> ?? matches.ToArray();
        return new ArchiveItemCatalogPage(
            materialized.Count,
            materialized.Skip(pageStart).Take(pageSize).ToArray());
    }

    private static ArchiveItemCatalogRecord NormalizeRecord(ArchiveItemCatalogRecord source)
    {
        var internalName = source.InternalName.Trim();
        var displayName = string.IsNullOrWhiteSpace(source.DisplayName)
            ? FriendlyName(internalName)
            : source.DisplayName.Trim();
        var localizedNames = NormalizeValues(source.LocalizedNames);
        var prefabHashes = (source.PrefabHashes ?? [])
            .Distinct()
            .ToArray();
        var pacFiles = NormalizeValues(source.PacFiles);
        var modelStems = NormalizeValues(source.ModelStems);
        var iconPaths = NormalizeValues(source.IconPaths);
        var materialTags = NormalizeValues(source.MaterialTags);
        var (category, group, categoryEvidence) = Classify(
            internalName,
            displayName,
            localizedNames,
            pacFiles,
            modelStems,
            iconPaths);
        var evidence = BuildEvidence(prefabHashes.Length > 0, modelStems.Length > 0, displayName, iconPaths, materialTags);
        var searchText = BuildSearchText(
            source.ItemId,
            internalName,
            displayName,
            category,
            group,
            localizedNames,
            pacFiles,
            modelStems,
            iconPaths,
            materialTags);
        return source with
        {
            InternalName = internalName,
            DisplayName = displayName,
            Category = category,
            Group = group,
            CategoryEvidence = categoryEvidence,
            PacFiles = pacFiles,
            ModelStems = modelStems,
            IconPaths = iconPaths,
            LocalizedNames = localizedNames,
            PrefabHashes = prefabHashes,
            MaterialTags = materialTags,
            VariantCount = Math.Max(1, source.VariantCount),
            Evidence = evidence,
            SearchText = searchText,
        };
    }

    private static string BuildGroupKey(ArchiveItemCatalogRecord item)
    {
        var displayBase = DisplayVariantSuffix.Replace(item.DisplayName, string.Empty).Trim();
        var internalBase = InternalVariantSuffix.Replace(item.InternalName, string.Empty).Trim('_');
        var scope = item.PacFiles
            .Concat(item.ModelStems)
            .Select(StripModelVariant)
            .Where(static value => value.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Order(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var identity = string.IsNullOrWhiteSpace(displayBase) ? internalBase : displayBase;
        return $"{identity}|{(scope.Length > 0 ? string.Join('|', scope) : internalBase)}";
    }

    private static ArchiveItemCatalogRecord MergeVariants(IGrouping<string, ArchiveItemCatalogRecord> group)
    {
        var rows = group.ToArray();
        var first = rows[0];
        if (rows.Length == 1)
        {
            return first;
        }
        static string[] MergeStrings(IEnumerable<IReadOnlyList<string>> sources) => sources
            .SelectMany(static values => values)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var displayName = DisplayVariantSuffix.Replace(first.DisplayName, string.Empty).Trim();
        var localizedNames = MergeStrings(rows.Select(static row => row.LocalizedNames));
        var pacFiles = MergeStrings(rows.Select(static row => row.PacFiles));
        var modelStems = MergeStrings(rows.Select(static row => row.ModelStems));
        var iconPaths = MergeStrings(rows.Select(static row => row.IconPaths));
        var materialTags = MergeStrings(rows.Select(static row => row.MaterialTags));
        var evidence = string.Join(
            "; ",
            rows.Select(static row => row.Evidence)
                .Where(static value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.OrdinalIgnoreCase));
        return first with
        {
            DisplayName = displayName,
            LocalizedNames = localizedNames,
            PrefabHashes = rows.SelectMany(static row => row.PrefabHashes).Distinct().ToArray(),
            PacFiles = pacFiles,
            ModelStems = modelStems,
            IconPaths = iconPaths,
            MaterialTags = materialTags,
            VariantCount = rows.Sum(static row => Math.Max(1, row.VariantCount)),
            Evidence = evidence,
            SearchText = BuildSearchText(
                first.ItemId,
                first.InternalName,
                displayName,
                first.Category,
                first.Group,
                localizedNames,
                pacFiles,
                modelStems,
                iconPaths,
                materialTags)
                + string.Join(' ', rows.Select(static row => $" {row.ItemId} {NormalizeSearchText(row.InternalName)} ")),
        };
    }

    private static string StripModelVariant(string value)
    {
        var basename = Path.GetFileNameWithoutExtension(value.Replace('\\', '/')).Trim().ToLowerInvariant();
        while (true)
        {
            var stripped = ModelTrailingLetterVariant.Replace(
                ModelVariantSuffix.Replace(basename, string.Empty),
                string.Empty).Trim('_');
            if (stripped == basename || stripped.Length == 0)
            {
                return basename;
            }
            basename = stripped;
        }
    }

    private static string BuildSearchText(
        int itemId,
        string internalName,
        string displayName,
        string category,
        string group,
        IReadOnlyList<string> localizedNames,
        IReadOnlyList<string> pacFiles,
        IReadOnlyList<string> modelStems,
        IReadOnlyList<string> iconPaths,
        IReadOnlyList<string> materialTags) => string.Join(
            ' ',
            new[]
            {
                internalName,
                displayName,
                category,
                group,
                string.Join(' ', localizedNames),
                string.Join(' ', pacFiles),
                string.Join(' ', modelStems),
                string.Join(' ', iconPaths),
                string.Join(' ', materialTags),
                itemId.ToString(System.Globalization.CultureInfo.InvariantCulture),
            }.Select(NormalizeSearchText));

    private static string[] NormalizeValues(IReadOnlyList<string>? values) =>
        (values ?? [])
            .Select(static value => value?.Trim() ?? string.Empty)
            .Where(static value => value.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

    private static string BuildEvidence(
        bool hasPrefabHashes,
        bool hasModelStems,
        string displayName,
        IReadOnlyList<string> iconPaths,
        IReadOnlyList<string> materialTags)
    {
        var parts = new List<string>();
        if (hasPrefabHashes) parts.Add("ItemInfo prefab hash");
        if (hasModelStems) parts.Add("icon/model reference");
        if (!string.IsNullOrWhiteSpace(displayName)) parts.Add("localized display name");
        if (iconPaths.Count > 0) parts.Add("inventory icon path");
        if (materialTags.Count > 0) parts.Add("material slot tags");
        return parts.Count > 0 ? string.Join("; ", parts) : "item database record";
    }

    private static (string Category, string Group, string Evidence) Classify(
        string internalName,
        string displayName,
        IReadOnlyList<string> localizedNames,
        IReadOnlyList<string> pacFiles,
        IReadOnlyList<string> modelStems,
        IReadOnlyList<string> iconPaths)
    {
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
        if (primaryNames.Any(static name => Regex.IsMatch(name ?? string.Empty, @"(?:^|[^a-z0-9])barding\s*$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)))
            return ("Mount / Pet", "Horse Gear", evidence);
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
                return ("Quest / Document", group, evidence);
        }
        var compactPrimary = CompactText(primaryText);
        if (compactPrimary.Contains("lostletter", StringComparison.Ordinal)
            || (compactPrimary.Contains("letter", StringComparison.Ordinal) && compactPrimary.EndsWith("letter", StringComparison.Ordinal)))
            return ("Quest / Document", "Document", evidence);
        if (CatalogTextMatchesAny(primaryText, "recipe", "craftingrecipe", "crafting recipe"))
            return ("Crafting / Recipe", "Recipe Book", evidence);
        if (CatalogTextMatchesAny(text, "itemcatch_fishingrod", "fishingrod", "fishing rod"))
            return ("Tool", "Fishing", evidence);
        if (CatalogTextMatchesAny(
                text,
                "petarmor", "pet armor", "catarmor", "cat armor", "dogarmor", "dog armor", "puppy",
                "cat outfit", "dog outfit", "pet outfit", "cat hat", "dog hat", "pet hat", "cat helm", "dog helm", "pet helm"))
            return ("Mount / Pet", "Pet Gear", evidence);
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
        var normalizedText = NormalizeSearchText(rawText);
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
            var normalizedToken = NormalizeSearchText(token).Trim();
            if (normalizedToken.Length > 0 && normalizedText.Contains($" {normalizedToken} ", StringComparison.Ordinal)) return true;
            var compactToken = CompactText(token);
            if (compactToken.Length >= 7 && compactText.Contains(compactToken, StringComparison.Ordinal)) return true;
        }
        return false;
    }

    private static string CompactText(string value)
    {
        var builder = new StringBuilder(value.Length);
        foreach (var ch in value)
        {
            if (ch is >= 'a' and <= 'z' or >= 'A' and <= 'Z' or >= '0' and <= '9')
            {
                builder.Append(char.ToLowerInvariant(ch));
            }
        }
        return builder.ToString();
    }

    private static string FriendlyName(string internalName)
    {
        var builder = new StringBuilder(internalName.Length + 8);
        for (var index = 0; index < internalName.Length; index++)
        {
            var ch = internalName[index];
            if (ch is '_' or '-')
            {
                builder.Append(' ');
                continue;
            }
            if (index > 0 && char.IsUpper(ch) && char.IsLower(internalName[index - 1]))
            {
                builder.Append(' ');
            }
            builder.Append(ch);
        }
        var words = builder.ToString().Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return string.Join(' ', words.Select(static word => char.ToUpperInvariant(word[0]) + word[1..]));
    }

    private static string[] Tokenize(string? value) => NormalizeSearchText(value ?? string.Empty)
        .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private static string NormalizeSearchText(string value)
    {
        var builder = new StringBuilder(value.Length + 2);
        builder.Append(' ');
        var priorWasSpace = true;
        foreach (var ch in value)
        {
            if (char.IsLetterOrDigit(ch))
            {
                builder.Append(char.ToLowerInvariant(ch));
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

    private sealed class CategoryGroupComparer : IEqualityComparer<(string Category, string Group)>
    {
        public static CategoryGroupComparer Instance { get; } = new();

        public bool Equals((string Category, string Group) x, (string Category, string Group) y) =>
            x.Category.Equals(y.Category, StringComparison.OrdinalIgnoreCase)
            && x.Group.Equals(y.Group, StringComparison.OrdinalIgnoreCase);

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
    IReadOnlyList<string> MaterialTags,
    string Category = "",
    string Group = "",
    string CategoryEvidence = "",
    int VariantCount = 1,
    string Evidence = "",
    [property: JsonIgnore] string SearchText = "");

public sealed record ArchiveItemCatalogPage(
    long TotalMatches,
    IReadOnlyList<ArchiveItemCatalogRecord> Items);
