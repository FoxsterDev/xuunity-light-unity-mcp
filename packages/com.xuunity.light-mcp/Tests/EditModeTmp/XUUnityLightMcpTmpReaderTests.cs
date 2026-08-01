using NUnit.Framework;
using TMPro;
using UnityEngine;
using UnityEngine.TestTools;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditModeTmp
{
    /// <summary>
    /// The TMP reader had no test assembly at all, so nothing exercised the reader that owns the
    /// exact defect this toolchain was built for: body copy that does not render.
    ///
    /// The unresolved font branch stays production-only on purpose. TMP substitutes its default font
    /// asset in both the `font` setter and `OnValidate`, so a project with TMP Essentials imported
    /// cannot hold a TMP label with a null font asset at all; the branch's real trigger is a project
    /// with no default font asset configured. Asserting it from here produced a permanently red test,
    /// which is worse than an honestly named gap.
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
            // Creating a TMP label touches font asset setup, which logs "No graphic device is
            // available to initialize the view" on a headless 2021.3 runner. The reader under test
            // reads serialized state and does not need a device, so the message is not a failure.
            LogAssert.ignoreFailingMessages = true;

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
            LogAssert.ignoreFailingMessages = false;
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
            CollectionAssert.Contains(
                new[] { "resolved", "unresolved" },
                body.font_resolved_status,
                "font_resolved_status is read by the explanation lane and must be populated");
            CollectionAssert.Contains(
                new[] { "resolved", "unresolved", "font_without_material" },
                body.material_resolved_status,
                "material_resolved_status is read by the explanation lane and must be populated");
        }

        /// <summary>
        /// The reader's `font_resolved_status: "unresolved"` branch is real but is not reachable from a
        /// test in this project: TMP substitutes the default font asset both in the `font` setter and
        /// again in `OnValidate`, so neither `font = null` nor writing `m_fontAsset` through
        /// SerializedObject survives. Its actual trigger is a project whose TMP settings carry no
        /// default font asset — TMP Essentials not imported — which onboarding hits, not a prefab an
        /// operator can author. What is reachable, and what an operator must not be misled by, is the
        /// substitution itself: a label nobody assigned a font to reports a resolved font, and the
        /// evidence has to name it so the substitution is visible rather than silent.
        /// </summary>
        [Test]
        public void Reader_NamesTheSubstitutedFontOnALabelThatWasNeverAssignedOne()
        {
            var orphan = NewChild("FontlessBody");
            orphan.AddComponent<TextMeshProUGUI>().text = "No font asset assigned";

            var label = orphan.GetComponent<TextMeshProUGUI>();
            var node = RunTree().nodes.Find(item => item.name == "FontlessBody");

            Assert.That(node, Is.Not.Null);

            // Whether TMP has a default font asset to substitute depends on TMP Essential Resources
            // being imported, which a bare CI project does not have. The invariant that matters to
            // the explanation lane holds either way: the status and the named font must agree, so a
            // substituted font is never reported as unresolved and an absent one is never reported
            // as resolved with no name.
            if (label.font != null)
            {
                Assert.That(
                    node.font_resolved_status,
                    Is.EqualTo("resolved"),
                    "TMP substituted its default font asset; reporting unresolved here would be wrong");
                Assert.That(
                    node.font,
                    Is.Not.Empty,
                    "a resolved font must be named, or the substitution is invisible to the operator");
            }
            else
            {
                Assert.That(
                    node.font_resolved_status,
                    Is.EqualTo("unresolved"),
                    "no font asset was available to substitute, which is exactly the unresolved case");
                Assert.That(node.font, Is.Empty);
            }
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
