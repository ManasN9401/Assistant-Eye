import time
from core.settings import Settings
from core.function_registry import FunctionRegistry
from core.ai_engine import AIEngine
from bridge.playwright_bridge import PlaywrightBridge, ActionExecutor

# Use local settings path
settings = Settings()
settings.set('active_site_url', 'http://localhost:5500')
settings.set('ai_provider', 'openai')
settings.set('ai_model', 'gpt-3.5-turbo')
settings.set('tts_enabled', False)

# Load built-in registry (should be created on init)
registry = FunctionRegistry(settings)

# Ensure the built-in registry is loaded and active
# user's code automatically sets up novausite in registry dir
registry_path = str(registry.registry_dir / 'novasuite.json')
loaded = registry.load(registry_path)
print('Registry loaded:', loaded)
print('Active site:', registry.get_active().get('site'))

engine = AIEngine(settings)
playwright = PlaywrightBridge(settings, engine)
executor = ActionExecutor(settings, engine, playwright, None)

print('Launching Playwright browser to active site...')
import asyncio
async def run_test():
    await playwright.launch(headless=False, url='http://localhost:5500')
    # verify current URL
    url = await playwright.evaluate('window.location.href')
    print('Opened URL:', url)

    # Execute a navigation action
    fn = next((f for f in registry.get_active()['functions'] if f['name']=='go_to_pricing'), None)
    if not fn:
        raise RuntimeError('go_to_pricing function not found')

    res = await executor._execute_async(fn, {})
    print('Action executor response:', res)
    await asyncio.sleep(1)
    url2 = await playwright.evaluate('window.location.href')
    print('URL after action:', url2)
    # run JS action (go_to_home) to check JS path
    fn2 = next((f for f in registry.get_active()['functions'] if f['name']=='go_to_home'), None)
    res2 = await executor._execute_async(fn2, {})
    print('Action executor response 2:', res2)
    await asyncio.sleep(1)
    url3 = await playwright.evaluate('window.location.href')
    print('URL after action 2:', url3)

    # sanity check: action via AI response block (simulate)
    # not needed for now

    await playwright.close()

asyncio.run(run_test())
print('Test script complete')
