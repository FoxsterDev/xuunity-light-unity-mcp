using NUnit.Framework;
using TMPro;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditModeTmp
{
    /// <summary>
    /// The TMP reader had no test assembly at all, so nothing exercised the reader that owns the
    /// exact defect this toolchain was built for: body copy that does not render. The unresolved
    /// font and material branches were reachable only in production.
    /// </summary>
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiReadTmp")]
    public sealed class XUUnityLightMcpTmpReaderTests
    {
        GameObject _canvasRoot;

        [SetUp]
        public void SetUp()
        {
            _canvasRoot = new GameObject("XUUnityMcp_TmpCanvas", typeof(RectTransform), typeof(Canvas));
            _canvasRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            _canvasRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var body = NewChild("Body");
            var bodyText = body.AddComponent<TextMeshProUGUI>();
            bodyText.text = "Boost your earnings for the next few minutes.";

            var empty = NewChild("EmptyBody");
            empty.AddComponent<TextMeshProUGUI>().text = "";

            var transparent = NewChild("TransparentBody");
            var transparentText = transparent.AddComponent<TextMeshProUGUI>();
            transparentText.text = "White on white";
            transparentText.color = new Color(1f, 1f, 1f, 0f);
        }

        [TearDown]
        public void TearDown()
        {
            if (_canvasRoot != null)
            {
                Object.DestroyImmediate(_canvasRoot);
                _canvasRoot = null;
            }
        }

        [Test]
        public void Reader_IsRegisteredAndReportedInTheSnapshot()
        {
            var payload = RunTree();

            CollectionAssert.Contains(payload.component_detail_backends, "textmeshpro");
            Assert.That(
                payload.warnings.Exists(item => item.code == "ui_component_details_unavailable"),
                Is.False);
        }

        [Test]
        public void Reader_ExtractsTmpTextAndNamesItsSource()
        {
            var body = RunTree().nodes.Find(node => node.name == "Body");

            Assert.That(body, Is.Not.Null);
            Assert.That(body.has_text, Is.True);
            Assert.That(body.text, Is.EqualTo("Boost your earnings for the next few minutes."));
            Assert.That(body.text_source, Is.EqualTo("TMPro.TMP_Text"));
        }

        [Test]
        public void Reader_ReportsEmptyCopyAsTextThatIsPresentButBlank()
        {
            var empty = RunTree().nodes.Find(node => node.name == "EmptyBody");

            // The distinction the retro needed: a label that exists and renders nothing is not the
            // same finding as a label that is missing from the tree.
            Assert.That(empty, Is.Not.Null);
            Assert.That(empty.has_text, Is.True);
            Assert.That(empty.text, Is.Empty);
        }

        [Test]
        public void Reader_TreatsFullyTransparentTmpTextAsInvisible()
        {
            var transparent = RunTree().nodes.Find(node => node.name == "TransparentBody");

            Assert.That(transparent, Is.Not.Null);
            Assert.That(transparent.active_in_hierarchy, Is.True);
            Assert.That(transparent.effective_alpha, Is.EqualTo(0f).Within(0.001f));
            Assert.That(transparent.visible, Is.False, "alpha-0 copy is present but not visible");
        }

        [Test]
        public void Reader_ReportsFontAndMaterialResolutionStatus()
        {
            var body = RunTree().nodes.Find(node => node.name == "Body");

            Assert.That(body, Is.Not.Null);
            // Whichever way the project's TMP defaults resolve, the status must be one of the
            // documented values the host branches on, never blank.
            Assert.That(
                body.font_resolved_status,
                Is.AnyOf("resolved", "unresolved"),
                "font_resolved_status is read by the explanation lane and must be populated");
            Assert.That(
                body.material_resolved_status,
                Is.AnyOf("resolved", "unresolved", "font_without_material"),
                "material_resolved_status is read by the explanation lane and must be populated");
        }

        [Test]
        public void Reader_FlagsAFontlessLabelAsUnresolved()
        {
            var orphan = NewChild("FontlessBody");
            var orphanText = orphan.AddComponent<TextMeshProUGUI>();
            orphanText.text = "No font asset";
            orphanText.font = null;

            var node = RunTree().nodes.Find(item => item.name == "FontlessBody");

            Assert.That(node, Is.Not.Null);
            Assert.That(node.font_resolved_status, Is.EqualTo("unresolved"));
        }

        GameObject NewChild(string name)
        {
            var child = new GameObject(name, typeof(RectTransform));
            child.transform.SetParent(_canvasRoot.transform, false);
            child.GetComponent<RectTransform>().sizeDelta = new Vector2(400f, 100f);
            return child;
        }

        static XUUnityLightMcpUiTreePayload RunTree()
        {
            var response = new XUUnityLightMcpUiTreeSnapshotOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "tmp-tree-selftest",
                operation = "unity.ui.tree_snapshot",
                args_json = "{\"targetKind\":\"active_scene\",\"includeInactive\":true}"
            });
            return JsonUtility.FromJson<XUUnityLightMcpUiTreePayload>(response.payload_json);
        }
    }
}
