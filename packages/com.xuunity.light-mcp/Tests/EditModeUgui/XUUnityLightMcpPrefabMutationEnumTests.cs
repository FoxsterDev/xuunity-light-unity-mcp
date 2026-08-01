using System.IO;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditModeUgui
{
    /// <summary>
    /// Enum addressing is the defect that shipped a wrong font weight behind a success receipt: enum
    /// properties are addressed by member index while a caller naturally supplies the enum's underlying
    /// value, and out-of-range input was clamped instead of rejected.
    ///
    /// These cases live in the uGUI test assembly because they need a managed `[SerializeField]` enum.
    /// Built-in components serialize their enums natively and SerializedProperty reports those as
    /// integers, so `Image.m_Type` is the nearest stable multi-member enum to exercise.
    /// </summary>
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.PrefabMutation")]
    public sealed class XUUnityLightMcpPrefabMutationEnumTests
    {
        const string PREFAB_DIR = "Assets/XUUnityLightMcpGenerated/MutationEnumSelfTest";
        const string ROOT_NAME = "XUUnityMcp_EnumRoot";

        string _prefabPath = "";

        [SetUp]
        public void SetUp()
        {
            Directory.CreateDirectory(PREFAB_DIR);
            AssetDatabase.Refresh();

            var root = new GameObject(ROOT_NAME, typeof(RectTransform), typeof(Image));
            root.GetComponent<Image>().type = Image.Type.Simple;
            _prefabPath = PREFAB_DIR + "/" + ROOT_NAME + ".prefab";
            PrefabUtility.SaveAsPrefabAsset(root, _prefabPath);
            Object.DestroyImmediate(root);
            AssetDatabase.Refresh();
        }

        [TearDown]
        public void TearDown()
        {
            if (!string.IsNullOrEmpty(_prefabPath))
            {
                AssetDatabase.DeleteAsset(_prefabPath);
                AssetDatabase.DeleteAsset(PREFAB_DIR);
                _prefabPath = "";
            }

            AssetDatabase.Refresh();
        }

        [Test]
        public void AnOutOfRangeEnumIndexIsRejectedInsteadOfSilentlyDiscarded()
        {
            var payload = Mutate("\"numberValue\":900");

            Assert.That(payload.status, Is.EqualTo("rolled_back"));
            Assert.That(payload.changes[0].error_code, Is.EqualTo("prefab_mutation_enum_value_invalid"));
            Assert.That(payload.changes[0].error_message, Does.Contain("is the member index"));
            Assert.That(payload.changes[0].error_message, Does.Contain("Valid members (name=index)"));
        }

        [Test]
        public void EnumsAreSettableByMemberNameAndReceiptedByName()
        {
            var payload = Mutate("\"stringValue\":\"Sliced\"");

            Assert.That(payload.status, Is.EqualTo("applied"), payload.changes[0].error_message);
            Assert.That(payload.changes[0].before, Is.EqualTo("Simple"));
            Assert.That(
                payload.changes[0].after,
                Is.EqualTo("Sliced"),
                "an enum receipt names the member, so the inverse patch can be replayed by name");
            Assert.That(payload.reversible_patch_json, Does.Contain("\"restoreValue\":\"Simple\""));

            var saved = AssetDatabase.LoadAssetAtPath<GameObject>(_prefabPath);
            Assert.That(saved.GetComponent<Image>().type, Is.EqualTo(Image.Type.Sliced));
        }

        [Test]
        public void AnUnknownEnumMemberNameIsRejectedWithTheValidMembers()
        {
            var payload = Mutate("\"stringValue\":\"NotAMemberOfThisEnum\"");

            Assert.That(payload.status, Is.EqualTo("rolled_back"));
            Assert.That(payload.changes[0].error_code, Is.EqualTo("prefab_mutation_enum_value_invalid"));
            Assert.That(payload.changes[0].error_message, Does.Contain("Simple=0"));
        }

        [Test]
        public void SettingAnEnumToTheValueItAlreadyHoldsIsReportedAsNoOp()
        {
            var payload = Mutate("\"stringValue\":\"Simple\"");

            Assert.That(payload.status, Is.EqualTo("applied"), "the transaction still succeeds");
            Assert.That(payload.changes[0].status, Is.EqualTo("no_op"));
            Assert.That(payload.no_op_count, Is.EqualTo(1));
        }

        XUUnityLightMcpPrefabMutationPayload Mutate(string valueJson)
        {
            var args = "{\"prefabPath\":\"" + _prefabPath + "\",\"approve\":true,\"previewOnly\":false,\"operations\":["
                       + "{\"op\":\"set_serialized_field\",\"path\":\"" + ROOT_NAME + "\",\"componentType\":\"Image\","
                       + "\"propertyPath\":\"m_Type\"," + valueJson + "}]}";
            var response = new XUUnityLightMcpPrefabMutateOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "prefab-mutate-enum-selftest",
                operation = "unity.prefab.mutate",
                args_json = args
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpPrefabMutationPayload>(response.payload_json);
        }
    }
}
