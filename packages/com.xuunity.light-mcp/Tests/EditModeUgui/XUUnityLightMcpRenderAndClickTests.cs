using System.IO;
using NUnit.Framework;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Ugui;

namespace XUUnity.LightMcp.Tests.EditModeUgui
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiRenderClick")]
    public sealed class XUUnityLightMcpRenderAndClickTests
    {
        const string GENERATED_ROOT = "Assets/XUUnityLightMcpGenerated";
        const string PREFAB_DIR = GENERATED_ROOT + "/RenderSelfTest";

        string _prefabPath = "";
        string _outputPath = "";
        GameObject _canvasRoot;
        int _clickCount;

        [SetUp]
        public void SetUp()
        {
            _clickCount = 0;
            Directory.CreateDirectory(PREFAB_DIR);
            AssetDatabase.Refresh();

            var root = new GameObject("XUUnityMcp_RenderRoot", typeof(RectTransform), typeof(Image));
            var rect = root.GetComponent<RectTransform>();
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
            root.GetComponent<Image>().color = new Color(0.2f, 0.6f, 0.9f, 1f);

            var label = new GameObject("Title", typeof(RectTransform), typeof(Text));
            label.transform.SetParent(root.transform, false);
            label.GetComponent<Text>().text = "Rendered";

            _prefabPath = PREFAB_DIR + "/XUUnityMcp_RenderRoot.prefab";
            PrefabUtility.SaveAsPrefabAsset(root, _prefabPath);
            Object.DestroyImmediate(root);
            AssetDatabase.Refresh();
        }

        [TearDown]
        public void TearDown()
        {
            if (_canvasRoot != null)
            {
                Object.DestroyImmediate(_canvasRoot);
                _canvasRoot = null;
            }

            if (!string.IsNullOrEmpty(_outputPath) && File.Exists(_outputPath))
            {
                File.Delete(_outputPath);
                _outputPath = "";
            }

            if (!string.IsNullOrEmpty(_prefabPath))
            {
                AssetDatabase.DeleteAsset(_prefabPath);
                AssetDatabase.DeleteAsset(PREFAB_DIR);
                _prefabPath = "";
            }
        }

        [Test]
        public void Render_ProducesAPngAtTheDeclaredViewportWithoutBootingTheApp()
        {
            var scene = SceneManager.GetActiveScene();
            var rootCountBefore = scene.rootCount;

            var payload = Render(240, 480);

            Assert.That(payload.success, Is.True, string.Join("; ", payload.errors.ConvertAll(item => item.message)));
            Assert.That(payload.application_booted, Is.False);
            Assert.That(payload.persisted_scene_changes, Is.False);
            Assert.That(File.Exists(payload.screenshot_path), Is.True);
            Assert.That(payload.screenshot_width, Is.EqualTo(240));
            Assert.That(payload.screenshot_height, Is.EqualTo(480));
            Assert.That(payload.screenshot_size_bytes, Is.GreaterThan(0));
            Assert.That(
                SceneManager.GetActiveScene().rootCount,
                Is.EqualTo(rootCountBefore),
                "the preview scene must not leak objects into the open scene");
        }

        [Test]
        public void Render_DrawsTheActualPrefabPixelsWhenAGraphicsDeviceIsPresent()
        {
            if (SystemInfo.graphicsDeviceType == UnityEngine.Rendering.GraphicsDeviceType.Null)
            {
                Assert.Ignore("Headless batchmode has no graphics device; pixel content cannot be verified here.");
            }

            var payload = Render(240, 480);
            Assert.That(payload.success, Is.True);

            var texture = new Texture2D(2, 2);
            try
            {
                Assert.That(texture.LoadImage(File.ReadAllBytes(payload.screenshot_path)), Is.True);
                Assert.That(texture.width, Is.EqualTo(240));
                Assert.That(texture.height, Is.EqualTo(480));

                var centre = texture.GetPixel(120, 240);
                Assert.That(centre.a, Is.GreaterThan(0.5f), "the rendered prefab should fill the viewport");
                Assert.That(
                    centre.b,
                    Is.GreaterThan(centre.r),
                    "the prefab's blue Image should dominate the centre pixel");
            }
            finally
            {
                Object.DestroyImmediate(texture);
            }
        }

        [Test]
        public void Render_ReturnsTheSnapshotItRenderedInRenderPixelSpace()
        {
            var payload = Render(240, 480);

            Assert.That(payload.snapshot, Is.Not.Null);
            Assert.That(payload.snapshot.target.capture_width, Is.EqualTo(240));
            Assert.That(payload.snapshot.target.capture_height, Is.EqualTo(480));
            Assert.That(payload.snapshot.node_count, Is.GreaterThanOrEqualTo(2));

            var title = payload.snapshot.nodes.Find(node => node.name == "Title");
            Assert.That(title, Is.Not.Null);
            Assert.That(title.has_text, Is.True);
            Assert.That(title.text, Is.EqualTo("Rendered"));
            Assert.That(title.has_bounds, Is.True);
        }

        [Test]
        public void Render_AppliesDeclaredSafeAreaInsets()
        {
            var payload = Render(240, 480, safeAreaTop: 40, safeAreaBottom: 20);

            Assert.That(payload.safe_area.y, Is.EqualTo(40f));
            Assert.That(payload.safe_area.height, Is.EqualTo(420f));
        }

        [Test]
        public void Render_RefusesAnInvalidViewportAndAnAllConsumingSafeArea()
        {
            var noViewport = Render(0, 0);
            Assert.That(noViewport.success, Is.False);
            Assert.That(noViewport.errors[0].code, Is.EqualTo("prefab_render_viewport_invalid"));

            var swallowed = Render(240, 480, safeAreaTop: 300, safeAreaBottom: 300);
            Assert.That(swallowed.success, Is.False);
            Assert.That(swallowed.errors[0].code, Is.EqualTo("prefab_render_safe_area_invalid"));
        }

        [Test]
        public void Render_RefusesAMissingPrefab()
        {
            var response = new XUUnityLightMcpPrefabRenderOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "render-missing",
                operation = "unity.prefab.render",
                args_json = "{\"prefabPath\":\"Assets/XUUnityMcp_NoSuchPrefab.prefab\",\"width\":240,\"height\":480}"
            });
            var payload = JsonUtility.FromJson<XUUnityLightMcpPrefabRenderPayload>(response.payload_json);

            Assert.That(payload.success, Is.False);
            Assert.That(payload.errors[0].code, Is.EqualTo("prefab_not_found"));
        }

        [Test]
        public void Click_RequiresExplicitApprovalAndTheClickAction()
        {
            BuildClickableCanvas();

            var unapproved = Click("{\"selector\":{\"name\":\"ClaimButton\"},\"action\":\"click\"}");
            Assert.That(unapproved.refusal_code, Is.EqualTo("ui_click_approval_required"));

            var wrongAction = Click("{\"selector\":{\"name\":\"ClaimButton\"},\"action\":\"drag\",\"approve\":true}");
            Assert.That(wrongAction.refusal_code, Is.EqualTo("ui_action_not_permitted"));
            Assert.That(_clickCount, Is.Zero);
        }

        [Test]
        public void Click_DeliversOnceToAUniqueInteractableTarget()
        {
            BuildClickableCanvas();

            var payload = Click("{\"selector\":{\"name\":\"ClaimButton\"},\"action\":\"click\",\"approve\":true}");

            Assert.That(payload.success, Is.True, payload.refusal_code);
            Assert.That(payload.delivered, Is.True);
            Assert.That(payload.status, Is.EqualTo("delivered"));
            Assert.That(payload.delivery_mechanism, Is.EqualTo("event_system_pointer_click_handler"));
            Assert.That(_clickCount, Is.EqualTo(1), "the click must be delivered exactly once");
            Assert.That(payload.before_snapshot.signature, Is.Not.Empty);
            Assert.That(payload.after_snapshot.signature, Is.Not.Empty);
        }

        [Test]
        public void Click_RefusesAmbiguousHiddenAndDisabledTargets()
        {
            BuildClickableCanvas();

            var ambiguous = Click("{\"selector\":{\"name\":\"Row\"},\"action\":\"click\",\"approve\":true}");
            Assert.That(ambiguous.refusal_code, Is.EqualTo("selector_ambiguous"));

            var hidden = Click("{\"selector\":{\"name\":\"HiddenButton\"},\"action\":\"click\",\"approve\":true}");
            Assert.That(hidden.refusal_code, Is.EqualTo("ui_target_not_visible"));

            var disabled = Click("{\"selector\":{\"name\":\"DisabledButton\"},\"action\":\"click\",\"approve\":true}");
            Assert.That(disabled.refusal_code, Is.EqualTo("ui_target_not_interactable"));

            Assert.That(_clickCount, Is.Zero, "no refusal path may deliver a click");
        }

        [Test]
        public void Click_RefusesATargetWithNoClickHandler()
        {
            BuildClickableCanvas();

            var payload = Click("{\"selector\":{\"name\":\"PlainPanel\"},\"action\":\"click\",\"approve\":true}");

            Assert.That(payload.refusal_code, Is.EqualTo("ui_target_has_no_click_handler"));
        }

        [Test]
        public void RenderAndClickOperationsAreRegisteredAndCapabilityGated()
        {
            foreach (var operation in new[] { "unity.prefab.render", "unity.ui.click" })
            {
                Assert.That(XUUnityLightMcpOperationRegistry.TryGet(operation, out _), Is.True, operation);
                Assert.That(
                    XUUnityLightMcpCapabilityRegistry.TryGetRequiredCapability(operation, out var capability),
                    Is.True,
                    operation);
                Assert.That(capability, Is.Not.Empty);
            }
        }

        void BuildClickableCanvas()
        {
            _canvasRoot = new GameObject("XUUnityMcp_ClickCanvas", typeof(RectTransform), typeof(Canvas));
            _canvasRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            _canvasRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var claim = NewButton("ClaimButton", interactable: true);
            claim.onClick.AddListener(() => _clickCount++);

            NewButton("DisabledButton", interactable: false);

            var hidden = NewButton("HiddenButton", interactable: true);
            hidden.GetComponent<Image>().color = new Color(1f, 1f, 1f, 0f);

            NewChild("Row");
            NewChild("Row");
            NewChild("PlainPanel");
        }

        Button NewButton(string name, bool interactable)
        {
            var child = NewChild(name);
            child.AddComponent<Image>();
            var button = child.AddComponent<Button>();
            button.interactable = interactable;
            return button;
        }

        GameObject NewChild(string name)
        {
            var child = new GameObject(name, typeof(RectTransform));
            child.transform.SetParent(_canvasRoot.transform, false);
            child.GetComponent<RectTransform>().sizeDelta = new Vector2(300f, 120f);
            return child;
        }

        XUUnityLightMcpPrefabRenderPayload Render(
            int width,
            int height,
            int safeAreaTop = 0,
            int safeAreaBottom = 0)
        {
            _outputPath = Path.Combine(Path.GetTempPath(), $"xuunity_render_{width}x{height}_{safeAreaTop}.png");
            var args = "{\"prefabPath\":\"" + _prefabPath + "\",\"width\":" + width + ",\"height\":" + height
                       + ",\"safeAreaTop\":" + safeAreaTop + ",\"safeAreaBottom\":" + safeAreaBottom
                       + ",\"outputPath\":\"" + _outputPath.Replace("\\", "/") + "\"}";
            var response = new XUUnityLightMcpPrefabRenderOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "prefab-render-selftest",
                operation = "unity.prefab.render",
                args_json = args
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpPrefabRenderPayload>(response.payload_json);
        }

        static XUUnityLightMcpUiClickPayload Click(string argsJson)
        {
            var response = new XUUnityLightMcpUiClickOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ui-click-selftest",
                operation = "unity.ui.click",
                args_json = argsJson
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpUiClickPayload>(response.payload_json);
        }
    }
}
