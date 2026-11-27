using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;

if (args.Length != 3)
    throw new ArgumentException("Usage: ComboPatch <vanilla MainChar_ComboTree.uasset> <staging root> <inspection root>");

var moves = new (string Name, string Package)[]
{
    ("YangPushKick", "/Game/YangMoves/YangPoweredPushKick"),
    ("YangRushSweep", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_Rush_Sweep_FL"),
    ("YangTripleHit", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_TripleHit_FL"),
    ("YangMultiHit", "/Game/YangMoves/YangUnblockableMultiHit")
};

BuildPoweredPushKick(args[2], args[1]);
BuildPrivateAttack(args[2], args[1], "P1Attacks/Yang_MultiHit", "YangUnblockableMultiHit",
    "YangMultiHitHitbox", expectedHitboxes: 10, expectedRows: 8);

foreach (var move in moves)
{
    var asset = new UAsset(args[0], EngineVersion.VER_UE4_26);
    if (!asset.VerifyBinaryEquality())
        throw new InvalidDataException("The input combo does not round-trip.");

    var combo = asset.Exports.OfType<NormalExport>().Single(export => export.ObjectName.ToString() == "MainChar_ComboTree");
    var attacks = combo.Data.OfType<MapPropertyData>().Single(item => item.Name.ToString() == "m_Attacks");
    var nodes = combo.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "m_Nodes");
    var starts = combo.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "m_ComboStartNodesContainer");
    var attackIndex = combo.Data.OfType<IntPropertyData>().First(item => item.Name.ToString() == "m_DefaultAttacks").Value;
    var node = (StructPropertyData)nodes.Value[attackIndex];
    var attackInfos = (StructPropertyData)node["m_AttackInfos"];
    var originalAttack = attackInfos.Value.OfType<NamePropertyData>().First();
    if (!originalAttack.Value.ToString().EndsWith(".MainChar_Jab_FR", StringComparison.Ordinal))
        throw new InvalidDataException("Unexpected default light attack in the input combo.");

    var path = move.Package + "." + move.Package.Split('/')[^1];
    var originalEntry = attacks.Value.Single(entry => entry.Key is NamePropertyData key && key.Value == originalAttack.Value);
    var originalImport = ((ObjectPropertyData)originalEntry.Value).Value.ToImport(asset);
    var outer = originalImport.OuterIndex.ToImport(asset);
    var packageIndex = asset.AddImport(new Import(outer.ClassPackage.ToString(), outer.ClassName.ToString(),
        new FPackageIndex(0), move.Package, false, asset));
    var attackImport = asset.AddImport(new Import(originalImport.ClassPackage.ToString(), originalImport.ClassName.ToString(),
        packageIndex, move.Package.Split('/')[^1], false, asset));

    var softKey = (NamePropertyData)originalEntry.Key.Clone();
    ReplacePath(softKey, asset, path);
    var hardValue = (ObjectPropertyData)originalEntry.Value.Clone();
    hardValue.Value = attackImport;
    attacks.Value.Add(softKey, hardValue);
    combo.SerializationBeforeSerializationDependencies.Add(attackImport);

    foreach (var slot in attackInfos.Value.OfType<NamePropertyData>())
        ReplacePath(slot, asset, path);
    var transitions = (StructPropertyData)node["m_Transitions"];
    ((ArrayPropertyData)transitions["m_Transitions"]).Value = [];

    // The default attack covers ordinary input. Drop contextual starts so that
    // a sprint, parry or proximity rule cannot select a different attack.
    starts.Value = [];
    combo.ObjectName = FName.FromString(asset, move.Name);

    var output = Path.Combine(args[1], "YangMoves", move.Name + ".uasset");
    Directory.CreateDirectory(Path.GetDirectoryName(output)!);
    asset.Write(output);

    var readback = new UAsset(output, EngineVersion.VER_UE4_26);
    var written = readback.Exports.OfType<NormalExport>().Single(export => export.ObjectName.ToString() == move.Name);
    var writtenNodes = written.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "m_Nodes");
    var writtenAttack = (StructPropertyData)((StructPropertyData)writtenNodes.Value[attackIndex])["m_AttackInfos"];
    var slots = writtenAttack.Value.OfType<NamePropertyData>().ToArray();
    if (slots.Length != 4 || slots.Any(slot => slot.Value.ToString() != path))
        throw new InvalidDataException("Attack reference verification failed.");
    Console.WriteLine($"{move.Name}: {path}");
}

static void ReplacePath(NamePropertyData slot, UAsset asset, string path)
{
    slot.Value = FName.FromString(asset, path);
}
static void BuildPoweredPushKick(string inspectionRoot, string stage)
{
    const float damage = 85;
    const float structureDamage = 360;
    const float knockbackDistance = 750; // Unreal centimeters
    const int freezeFrames = 11;
    const string pushBackTag = "Attack.HitProperties.PushBack";
    const string knockDownTag = "Attack.HitProperties.KnockDown";

    var (attack, table) = BuildPrivateAttack(inspectionRoot, stage, "P2Attacks/Yang_SidePushKick_FL",
        "YangPoweredPushKick", "YangPushKickHitbox", expectedHitboxes: 1, expectedRows: 1, tune: (asset, attack, row) =>
        {
            var tags = AttackTags(attack);
            var pushBack = Array.FindIndex(tags.Value, tag => tag.ToString() == pushBackTag);
            if (pushBack < 0 || row.Name.ToString() != "SidePushkick")
                throw new InvalidDataException("Unexpected source push kick configuration.");
            // Use the game's knockdown reaction as in Yang's spin high kick.
            tags.Value[pushBack] = FName.FromString(asset, knockDownTag);
            PushBackLevel(row).Value = 0;

            ((BoolPropertyData)row["m_bCanBreakStructure"]).Value = true;
            var hit = (StructPropertyData)row["m_OnHitImpact"];
            ((FloatPropertyData)hit["m_fDamage"]).Value = damage;
            ((BoolPropertyData)hit["m_bUseKnockBackDistance"]).Value = true;
            ((FloatPropertyData)hit["m_fKnockBackDistance"]).Value = knockbackDistance;
            ((IntPropertyData)hit["m_iFreezeFrames"]).Value = freezeFrames;
            foreach (var impact in new[] { "m_OnHitImpact", "m_OnGuardImpact", "m_OnDeflectImpact" })
                ((FloatPropertyData)((StructPropertyData)row[impact])["m_fStructureDamage"]).Value = structureDamage;
        });

    var tags = AttackTags(attack).Value.Select(tag => tag.ToString()).ToArray();
    var row = table.Table.Data.Single();
    var hit = (StructPropertyData)row["m_OnHitImpact"];
    if (!tags.Contains(knockDownTag) || tags.Contains(pushBackTag) || PushBackLevel(row).Value != 0 ||
        !((BoolPropertyData)row["m_bCanBreakStructure"]).Value ||
        !((BoolPropertyData)hit["m_bUseDamage"]).Value ||
        ((FloatPropertyData)hit["m_fDamage"]).Value != damage ||
        !((BoolPropertyData)hit["m_bUseFreezeFrames"]).Value ||
        ((IntPropertyData)hit["m_iFreezeFrames"]).Value != freezeFrames ||
        !((BoolPropertyData)hit["m_bUseKnockBackDistance"]).Value ||
        ((FloatPropertyData)hit["m_fKnockBackDistance"]).Value != knockbackDistance ||
        new[] { "m_OnHitImpact", "m_OnGuardImpact", "m_OnDeflectImpact" }.Any(name =>
        {
            var impact = (StructPropertyData)row[name];
            return !((BoolPropertyData)impact["m_bUseStructureDamage"]).Value ||
                ((FloatPropertyData)impact["m_fStructureDamage"]).Value != structureDamage;
        }))
        throw new InvalidDataException("Powered push kick verification failed.");
    Console.WriteLine($"Verified powered push kick: KnockDown, damage={damage}, structure={structureDamage}, knockback={knockbackDistance} cm, freeze={freezeFrames} frames.");
}

static GameplayTagContainerPropertyData AttackTags(StructPropertyData attack) =>
    ((StructPropertyData)attack["m_AttackProperties"]).Value.OfType<GameplayTagContainerPropertyData>().Single();

static UInt32PropertyData PushBackLevel(StructPropertyData row) =>
    ((StructPropertyData)row["m_AttackPropertyLevel"]).Value.OfType<UInt32PropertyData>()
        .Single(property => property.Name.ToString() == "m_Level" && property.ArrayIndex == 1);

static (StructPropertyData Attack, DataTableExport Table) BuildPrivateAttack(
    string inspectionRoot, string stage, string sourceAttack, string attackName, string tableName,
    int expectedHitboxes, int expectedRows, Action<UAsset, StructPropertyData, StructPropertyData>? tune = null)
{
    var content = Path.Combine(inspectionRoot, "Sifu", "Content");
    var source = Path.Combine(content, "DB", "AI", "Archetypes", "Yang", "Attacks");
    var attack = new UAsset(Path.Combine(source, sourceAttack + ".uasset"), EngineVersion.VER_UE4_26);
    var table = new UAsset(Path.Combine(source, "Yang_HitboxData.uasset"), EngineVersion.VER_UE4_26);
    if (!attack.VerifyBinaryEquality() || !table.VerifyBinaryEquality())
        throw new InvalidDataException($"{attackName} sources do not round-trip.");

    var definition = attack.Exports.OfType<NormalExport>().Single(export => export.ObjectName.ToString() == Path.GetFileName(sourceAttack));
    var attackData = definition.Data.OfType<StructPropertyData>().Single(property => property.Name.ToString() == "m_Attack");
    var hitboxes = (ArrayPropertyData)attackData["m_HitBoxes"];
    var usedRows = hitboxes.Value.Cast<StructPropertyData>().Select(hit =>
        ((NamePropertyData)((StructPropertyData)hit["m_HitRow"])["RowName"]).Value.ToString()).ToHashSet();
    if (hitboxes.Value.Length != expectedHitboxes || usedRows.Count != expectedRows)
        throw new InvalidDataException($"Unexpected {attackName} hit windows.");

    var tableExport = table.Exports.OfType<DataTableExport>().Single();
    tableExport.Table.Data.RemoveAll(row => !usedRows.Contains(row.Name.ToString()));
    if (tableExport.Table.Data.Count != usedRows.Count)
        throw new InvalidDataException($"Missing {attackName} hit data.");

    // EHitBoxDefenseMatrix values were read from this build's enum metadata.
    // Dodge=1, Deflect=2, Guard=4. A zero mask disables every defense.
    foreach (var row in tableExport.Table.Data)
    {
        ((IntPropertyData)row["m_iHitboxDefenseMatrix"]).Value = 0;
        ((IntPropertyData)row["m_iAvoidableDefenseMatrix"]).Value = 0;
        ((BoolPropertyData)row["m_bPlayAvoidedOrder"]).Value = false;
        ((BoolPropertyData)row["m_bHitAnyCharacterOnAvoid"]).Value = true;
        ((BoolPropertyData)row["m_bParriable"]).Value = false;
        tune?.Invoke(attack, attackData, row);
    }

    tableExport.ObjectName = FName.FromString(table, tableName);
    definition.ObjectName = FName.FromString(attack, attackName);
    var tableImport = attack.Imports.Single(import =>
        import.ClassName.ToString() == "DataTable" && import.ObjectName.ToString() == "Yang_HitboxData");
    tableImport.ObjectName = FName.FromString(attack, tableName);
    tableImport.OuterIndex.ToImport(attack).ObjectName = FName.FromString(attack, "/Game/YangMoves/" + tableName);

    var output = Path.Combine(stage, "YangMoves");
    Directory.CreateDirectory(output);
    var attackPath = Path.Combine(output, attackName + ".uasset");
    attack.Write(attackPath);
    var tablePath = Path.Combine(output, tableName + ".uasset");
    table.Write(tablePath);
    var readback = new UAsset(tablePath, EngineVersion.VER_UE4_26).Exports.OfType<DataTableExport>().Single();
    if (readback.ObjectName.ToString() != tableName ||
        !usedRows.SetEquals(readback.Table.Data.Select(row => row.Name.ToString())) ||
        readback.Table.Data.Any(row =>
        ((IntPropertyData)row["m_iHitboxDefenseMatrix"]).Value != 0 ||
        ((IntPropertyData)row["m_iAvoidableDefenseMatrix"]).Value != 0 ||
        ((BoolPropertyData)row["m_bPlayAvoidedOrder"]).Value ||
        !((BoolPropertyData)row["m_bHitAnyCharacterOnAvoid"]).Value ||
        ((BoolPropertyData)row["m_bParriable"]).Value))
        throw new InvalidDataException($"{attackName} defense/avoid verification failed.");

    var writtenAttack = new UAsset(attackPath, EngineVersion.VER_UE4_26);
    var writtenData = writtenAttack.Exports.OfType<NormalExport>()
        .Single(export => export.ObjectName.ToString() == attackName).Data.OfType<StructPropertyData>()
        .Single(property => property.Name.ToString() == "m_Attack");
    var writtenHitboxes = (ArrayPropertyData)writtenData["m_HitBoxes"];
    if (writtenHitboxes.Value.Length != expectedHitboxes || writtenHitboxes.Value.Cast<StructPropertyData>().Any(hit =>
        {
            var row = (StructPropertyData)hit["m_HitRow"];
            var import = ((ObjectPropertyData)row["DataTable"]).Value.ToImport(writtenAttack);
            return import.ObjectName.ToString() != tableName ||
                import.OuterIndex.ToImport(writtenAttack).ObjectName.ToString() != "/Game/YangMoves/" + tableName ||
                !usedRows.Contains(((NamePropertyData)row["RowName"]).Value.ToString());
        }))
        throw new InvalidDataException($"{attackName} private hit table reference verification failed.");
    Console.WriteLine($"Verified {expectedRows} private {attackName} hit rows with Guard/Deflect/Dodge/Avoid disabled.");
    return (writtenData, readback);
}
