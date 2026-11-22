using System.Text.Json;
using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;

if (args.Length != 3 || Path.GetFullPath(args[0]).Equals(Path.GetFullPath(args[1]), StringComparison.OrdinalIgnoreCase))
    throw new ArgumentException("GripSocketPatch <cooked source mesh> <staged mesh> <socket JSON>");

var meshAsset = new UAsset(args[0], EngineVersion.VER_UE4_26);
var meshName = Path.GetFileNameWithoutExtension(args[0]);
if (!meshAsset.VerifyBinaryEquality())
    throw new InvalidDataException("The cooked mesh does not round-trip through UAssetAPI.");
var mesh = meshAsset.Exports.OfType<NormalExport>().Single(e => e.ObjectName.ToString() == meshName);
var meshIndex = FPackageIndex.FromExport(meshAsset.Exports.IndexOf(mesh));
FName Name(string s) => FName.FromString(meshAsset, s);
FPackageIndex ImportIndex(string name) => FPackageIndex.FromImport(
    meshAsset.Imports.FindIndex(i => i.ObjectName.ToString() == name));
var engine = ImportIndex("/Script/Engine");
var nullIndex = FPackageIndex.FromRawIndex(0);
var socketClass = meshAsset.AddImport(new Import("/Script/CoreUObject", "Class", engine, "SkeletalMeshSocket", false, meshAsset));
var socketClassDefault = meshAsset.AddImport(new Import("/Script/Engine", "SkeletalMeshSocket", engine,
    "Default__SkeletalMeshSocket", false, meshAsset));
var sockets = JsonSerializer.Deserialize<SocketSpec[]>(File.ReadAllText(args[2]),
    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
if (sockets == null || sockets.Length == 0 || sockets.Select(s => s.Name).Distinct().Count() != sockets.Length)
    throw new InvalidDataException("Expected a nonempty list of unique weapon sockets.");
if (mesh["Sockets"] is ArrayPropertyData existing && existing.Value.Length != 0)
    throw new InvalidDataException("The base mesh already has sockets that must be preserved.");

var references = new List<PropertyData>();
foreach (var type in new[] { "ArrayProperty", "ObjectProperty", "NameProperty", "StructProperty", "Vector", "Rotator" })
    _ = Name(type);
foreach (var spec in sockets)
{
    if (spec.Position.Length != 3 || spec.Rotation.Length != 3 ||
        spec.Position.Concat(spec.Rotation).Any(v => !float.IsFinite(v)))
        throw new InvalidDataException("Socket transform must have three finite axes.");
    var location = Name("RelativeLocation");
    var rotation = Name("RelativeRotation");
    var properties = new List<PropertyData>
    {
        new NamePropertyData(Name("SocketName")) { Value = Name(spec.Name) },
        new NamePropertyData(Name("BoneName")) { Value = Name(spec.Bone) },
        new StructPropertyData(location, Name("Vector"))
        {
            Value = new() { new VectorPropertyData(location) { Value = new FVector(spec.Position[0], spec.Position[1], spec.Position[2]) } }
        },
        new StructPropertyData(rotation, Name("Rotator"))
        {
            Value = new() { new RotatorPropertyData(rotation) { Value = new FRotator(spec.Rotation[0], spec.Rotation[1], spec.Rotation[2]) } }
        }
    };
    var export = new NormalExport(properties, meshAsset, Array.Empty<byte>())
    {
        ObjectName = Name("NailoongGrip_" + spec.Name),
        OuterIndex = meshIndex,
        ClassIndex = socketClass,
        SuperIndex = nullIndex,
        TemplateIndex = socketClassDefault,
        ObjectFlags = EObjectFlags.RF_Public | EObjectFlags.RF_Transactional,
    };
    // The mesh is created before its subobjects. Their references can then be
    // serialized in the mesh without introducing a circular serialization dependency.
    export.CreateBeforeCreateDependencies.Add(meshIndex);
    export.CreateBeforeCreateDependencies.Add(socketClass);
    export.SerializationBeforeCreateDependencies.Add(socketClassDefault);
    var index = FPackageIndex.FromExport(meshAsset.Exports.Count);
    meshAsset.Exports.Add(export);
    mesh.CreateBeforeSerializationDependencies.Add(index);
    references.Add(new ObjectPropertyData(Name("Sockets")) { Value = index });
}

mesh["Sockets"] = new ArrayPropertyData(Name("Sockets"))
{
    ArrayType = Name("ObjectProperty"),
    Value = references.ToArray()
};
meshAsset.Write(args[1]);
var reloaded = new UAsset(args[1], EngineVersion.VER_UE4_26);
var reloadedMesh = reloaded.Exports.OfType<NormalExport>().Single(e => e.ObjectName.ToString() == meshName);
var stored = ((ArrayPropertyData)reloadedMesh["Sockets"]).Value.Cast<ObjectPropertyData>()
    .Select(p => (NormalExport)p.Value.ToExport(reloaded)).ToArray();
if (stored.Length != sockets.Length)
    throw new InvalidDataException("The socket array did not round-trip.");
for (var i = 0; i < sockets.Length; i++)
{
    var socket = stored[i];
    var location = ((VectorPropertyData)((StructPropertyData)socket["RelativeLocation"]).Value.Single()).Value;
    if (((NamePropertyData)socket["SocketName"]).Value.ToString() != sockets[i].Name ||
        ((NamePropertyData)socket["BoneName"]).Value.ToString() != sockets[i].Bone ||
        socket.OuterIndex.Index != meshIndex.Index ||
        Math.Abs(location.X - sockets[i].Position[0]) > .001 ||
        Math.Abs(location.Y - sockets[i].Position[1]) > .001 ||
        Math.Abs(location.Z - sockets[i].Position[2]) > .001)
        throw new InvalidDataException("Unexpected socket after reload.");
}
Console.WriteLine($"Verified {stored.Length} mesh-only socket exports.");

record SocketSpec(string Name, string Bone, float[] Position, float[] Rotation);
