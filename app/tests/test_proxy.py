import unittest
import os
import importlib
from unittest.mock import patch, MagicMock

# Assuming app.config and app.vertex_ai_init are accessible
# We might need to adjust sys.path if running tests from a different directory
import app.config
import app.vertex_ai_init

# Import requests for HTTP/HTTPS tests
import requests

# We'll need to potentially mock things from these modules
import socket
import socks # PySocks
import ssl

class TestHttpProxy(unittest.TestCase):
    def setUp(self):
        # Store original environment variables and socket.create_connection
        self.original_environ = os.environ.copy()
        self.original_create_connection = socket.create_connection
        self.original_sys_modules_config = sys.modules.get('app.config')
        self.original_sys_modules_vertex_ai_init = sys.modules.get('app.vertex_ai_init')


    def tearDown(self):
        # Restore original environment variables and socket.create_connection
        os.environ.clear()
        os.environ.update(self.original_environ)
        socket.create_connection = self.original_create_connection

        # Reset modules to ensure clean state for other tests
        if self.original_sys_modules_config:
            sys.modules['app.config'] = self.original_sys_modules_config
        else:
            if 'app.config' in sys.modules:
                del sys.modules['app.config']
        
        if self.original_sys_modules_vertex_ai_init:
            sys.modules['app.vertex_ai_init'] = self.original_sys_modules_vertex_ai_init
        else:
            if 'app.vertex_ai_init' in sys.modules:
                del sys.modules['app.vertex_ai_init']
        
        # Reload to be absolutely sure
        importlib.reload(app.config)
        importlib.reload(app.vertex_ai_init)


    @patch('socket.create_connection')
    def test_http_proxy_requests(self, mock_create_connection):
        os.environ['HTTP_PROXY'] = 'http://proxy.example.com:8080'
        os.environ.pop('HTTPS_PROXY', None)
        os.environ.pop('ALL_PROXY', None)

        # Reload app.config to pick up new environment variables
        # google-auth library reads environment variables when it's imported or when a session is created.
        # For requests, it typically checks env vars at the time of the request.
        
        # For this test, we are primarily testing if 'requests' itself honors HTTP_PROXY.
        # The application's config module (app.config) has already been updated to read HTTP_PROXY,
        # but it's 'requests' or 'google-auth' that will use it.
        # 'google-auth' uses 'requests'.

        try:
            requests.get("http://example.com", timeout=0.1)
        except requests.exceptions.Timeout:
            pass # Expected timeout as we are not actually connecting

        # Assert that socket.create_connection was called with proxy details
        # Requests will try to connect to proxy.example.com:8080
        mock_create_connection.assert_called_with(
            ("proxy.example.com", 8080), timeout=unittest.mock.ANY
        )

class TestHttpsProxy(unittest.TestCase):
    def setUp(self):
        self.original_environ = os.environ.copy()
        self.original_create_connection = socket.create_connection
        self.original_sys_modules_config = sys.modules.get('app.config')
        self.original_sys_modules_vertex_ai_init = sys.modules.get('app.vertex_ai_init')


    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_environ)
        socket.create_connection = self.original_create_connection
        if self.original_sys_modules_config:
            sys.modules['app.config'] = self.original_sys_modules_config
        else:
            if 'app.config' in sys.modules:
                del sys.modules['app.config']
        
        if self.original_sys_modules_vertex_ai_init:
            sys.modules['app.vertex_ai_init'] = self.original_sys_modules_vertex_ai_init
        else:
            if 'app.vertex_ai_init' in sys.modules:
                del sys.modules['app.vertex_ai_init']
        importlib.reload(app.config)
        importlib.reload(app.vertex_ai_init)


    @patch('socket.create_connection')
    @patch('ssl.wrap_socket', side_effect=lambda sock, *args, **kwargs: sock) # Mock wrap_socket to just return the socket
    def test_https_proxy_requests(self, mock_wrap_socket, mock_create_connection):
        os.environ['HTTPS_PROXY'] = 'http://secureproxy.example.com:8888' # HTTPS_PROXY can be an HTTP URL
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('ALL_PROXY', None)

        # Reload app.config (though less critical for `requests` which reads env directly)
        # importlib.reload(app.config)

        try:
            requests.get("https://example.com", timeout=0.1)
        except requests.exceptions.Timeout:
            pass

        # For HTTPS requests through an HTTP proxy, `requests` makes a CONNECT request to the proxy.
        # The initial connection is to the proxy.
        mock_create_connection.assert_called_with(
            ("secureproxy.example.com", 8888), timeout=unittest.mock.ANY
        )
        # We can also check that ssl.wrap_socket was called, as it's an HTTPS request,
        # though the connection itself is first to the proxy.
        # This part might be tricky because the SSL handshake happens *after* the CONNECT tunnel is established.
        # For this test, focusing on `create_connection` to the proxy is the primary goal.
        # If `requests` establishes a tunnel, `ssl.wrap_socket` would be called with the socket returned by `create_connection`.
        # self.assertTrue(mock_wrap_socket.called)


class TestSocksProxy(unittest.TestCase):
    def setUp(self):
        self.original_environ = os.environ.copy()
        self.original_socket_socket = socket.socket
        self.original_sys_modules_config = sys.modules.get('app.config')
        self.original_sys_modules_vertex_ai_init = sys.modules.get('app.vertex_ai_init')
        self.original_vertex_ai_init_func = app.vertex_ai_init.init_vertex_ai
        
        # It's crucial to reset PySocks' default proxy setting
        socks.set_default_proxy(None)


    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_environ)
        socket.socket = self.original_socket_socket # Restore original socket
        socks.set_default_proxy(None) # Clear any proxy settings in PySocks

        if self.original_sys_modules_config:
            sys.modules['app.config'] = self.original_sys_modules_config
        else:
            if 'app.config' in sys.modules:
                del sys.modules['app.config']
        
        if self.original_sys_modules_vertex_ai_init:
            sys.modules['app.vertex_ai_init'] = self.original_sys_modules_vertex_ai_init
        else:
            if 'app.vertex_ai_init' in sys.modules:
                del sys.modules['app.vertex_ai_init']

        # Restore the original init_vertex_ai function if it was modified
        app.vertex_ai_init.init_vertex_ai = self.original_vertex_ai_init_func

        importlib.reload(app.config)
        importlib.reload(app.vertex_ai_init)


    @patch('socks.set_default_proxy')
    @patch('socket.socket') # To check if it's replaced by socks.socksocket
    async def run_init_vertex_ai_with_env(self, env_vars, mock_socket_module_socket, mock_set_default_proxy):
        # Helper to run init_vertex_ai with patched environment and reloaded modules
        with patch.dict(os.environ, env_vars, clear=True):
            importlib.reload(app.config) # Reload config to pick up env vars
            # The SOCKS setup is at the top of app.vertex_ai_init.init_vertex_ai
            # We need to ensure app.config.ALL_PROXY is correctly set when init_vertex_ai is called.
            # We also need to mock the parts of init_vertex_ai that are not relevant to proxy setup,
            # like credential loading, to prevent side effects or errors.
            
            # For simplicity in this test, we assume app.vertex_ai_init.init_vertex_ai will be called
            # and the proxy logic at its beginning will execute.
            # A more robust approach might involve extracting proxy setup logic.
            
            # Mock parts of init_vertex_ai to prevent actual credential loading/validation
            with patch('app.vertex_ai_init.refresh_models_config_cache', return_value=True), \
                 patch('app.vertex_ai_init.CredentialManager') as MockCredentialManager, \
                 patch('google.genai.Client'): # Mock genai.Client if it's called for validation
                
                mock_credential_manager_instance = MockCredentialManager.return_value
                mock_credential_manager_instance.refresh_credentials_list.return_value = True # Simulate creds found
                mock_credential_manager_instance.get_total_credentials.return_value = 1
                mock_credential_manager_instance.get_random_credentials.return_value = (MagicMock(), "test-project")

                # Reload vertex_ai_init AFTER app.config is reloaded with new env vars
                importlib.reload(app.vertex_ai_init) 
                await app.vertex_ai_init.init_vertex_ai(mock_credential_manager_instance)
        return mock_set_default_proxy, mock_socket_module_socket


    @patch('socks.socksocket.connect') # Mock the connect method of socksocket instances
    async def test_socks5_proxy_applied_and_used(self, mock_socks_connect):
        env_vars = {
            'ALL_PROXY': 'socks5://user:pass@socksproxy.example.com:1080',
            # Keep other env vars minimal to avoid interference, or copy previous and update
        }
        
        # Run init_vertex_ai with the SOCKS proxy environment variables
        # This should call socks.set_default_proxy and change socket.socket
        mock_set_default_proxy_func, mock_socket_assignment = await self.run_init_vertex_ai_with_env(env_vars)

        mock_set_default_proxy_func.assert_called_with(
            socks.SOCKS5,
            addr="socksproxy.example.com",
            port=1080,
            username="user",
            password="pass",
            rdns=False 
        )
        self.assertEqual(socket.socket, socks.socksocket)

        # Now, simulate a network call that would use the default socket
        # (which should be socks.socksocket)
        # Example: A direct socket connection attempt
        try:
            # This would normally be done by a library like google-genai
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("target.example.com", 443))
        except Exception:
            # We expect an error because connect is mocked, or other issues.
            # The key is to check if mock_socks_connect was called.
            pass

        mock_socks_connect.assert_called_with(("target.example.com", 443))

    @patch('socks.socksocket.connect')
    async def test_socks5h_proxy_applied_rdns_true(self, mock_socks_connect):
        env_vars = {'ALL_PROXY': 'socks5h://user:pass@socksproxy.example.com:1080'}
        
        mock_set_default_proxy_func, _ = await self.run_init_vertex_ai_with_env(env_vars)

        mock_set_default_proxy_func.assert_called_with(
            socks.SOCKS5,
            addr="socksproxy.example.com",
            port=1080,
            username="user",
            password="pass",
            rdns=True # Key check for socks5h
        )
        self.assertEqual(socket.socket, socks.socksocket)
        
        # Similar to above, simulate a network call
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("target.example.com", 443))
        except Exception:
            pass
        mock_socks_connect.assert_called_with(("target.example.com", 443))


class TestNoProxy(unittest.TestCase):
    def setUp(self):
        self.original_environ = os.environ.copy()
        self.original_create_connection = socket.create_connection
        self.original_socket_socket = socket.socket
        self.original_sys_modules_config = sys.modules.get('app.config')
        self.original_sys_modules_vertex_ai_init = sys.modules.get('app.vertex_ai_init')
        self.original_vertex_ai_init_func = app.vertex_ai_init.init_vertex_ai

        # Clear any proxy settings from environment
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('HTTPS_PROXY', None)
        os.environ.pop('ALL_PROXY', None)
        
        # Reset PySocks' default proxy setting and restore original socket.socket
        socks.set_default_proxy(None)
        socket.socket = self.original_socket_socket # Ensure it's reset before each test

        # Reload modules to reflect clean environment
        importlib.reload(app.config)
        importlib.reload(app.vertex_ai_init)


    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_environ)
        socket.create_connection = self.original_create_connection
        socket.socket = self.original_socket_socket
        socks.set_default_proxy(None)

        if self.original_sys_modules_config:
            sys.modules['app.config'] = self.original_sys_modules_config
        else:
            if 'app.config' in sys.modules:
                del sys.modules['app.config']
        
        if self.original_sys_modules_vertex_ai_init:
            sys.modules['app.vertex_ai_init'] = self.original_sys_modules_vertex_ai_init
        else:
            if 'app.vertex_ai_init' in sys.modules:
                del sys.modules['app.vertex_ai_init']
        
        app.vertex_ai_init.init_vertex_ai = self.original_vertex_ai_init_func

        importlib.reload(app.config)
        importlib.reload(app.vertex_ai_init)

    @patch('socket.create_connection')
    async def test_no_http_proxy_direct_connection(self, mock_create_connection):
        # Ensure no proxy env vars are set (done in setUp)
        # Reload config to ensure it sees no proxy env vars
        # importlib.reload(app.config) # Done in setUp

        try:
            requests.get("http://example.com", timeout=0.1)
        except requests.exceptions.Timeout:
            pass

        # Connection should be direct to example.com
        mock_create_connection.assert_called_with(
            ("example.com", 80), timeout=unittest.mock.ANY # Port 80 for HTTP
        )

    @patch('socket.create_connection')
    @patch('ssl.wrap_socket', side_effect=lambda sock, *args, **kwargs: sock)
    async def test_no_https_proxy_direct_connection(self, mock_wrap_socket, mock_create_connection):
        # importlib.reload(app.config) # Done in setUp
        try:
            requests.get("https://example.com", timeout=0.1)
        except requests.exceptions.Timeout:
            pass

        # Connection should be direct to example.com
        mock_create_connection.assert_called_with(
            ("example.com", 443), timeout=unittest.mock.ANY # Port 443 for HTTPS
        )
        # self.assertTrue(mock_wrap_socket.called)


    @patch('socket.socket.connect') # Mock connect on the original socket class
    async def test_no_socks_proxy_direct_connection(self, mock_socket_connect):
        # Ensure ALL_PROXY is not set (done in setUp)
        # Reload config and vertex_ai_init
        # importlib.reload(app.config) # Done in setUp
        # importlib.reload(app.vertex_ai_init) # Done in setUp

        # Run init_vertex_ai to ensure SOCKS is not configured
        with patch('app.vertex_ai_init.refresh_models_config_cache', return_value=True), \
             patch('app.vertex_ai_init.CredentialManager') as MockCredentialManager, \
             patch('google.genai.Client'):
            mock_credential_manager_instance = MockCredentialManager.return_value
            mock_credential_manager_instance.refresh_credentials_list.return_value = True
            mock_credential_manager_instance.get_total_credentials.return_value = 1
            mock_credential_manager_instance.get_random_credentials.return_value = (MagicMock(), "test-project")

            await app.vertex_ai_init.init_vertex_ai(mock_credential_manager_instance)

        self.assertNotEqual(socket.socket, socks.socksocket) # Should be original socket

        # Simulate a network call
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("target.example.com", 443))
        except Exception:
            pass
        
        # If socket.socket was not changed to socks.socksocket, then its original connect should be called.
        mock_socket_connect.assert_called_with(("target.example.com", 443))


if __name__ == '__main__':
    # This allows running the tests directly, though usually a test runner is used.
    # For async tests, unittest.main() might not work directly without adjustments.
    # Consider using a test runner like `python -m unittest app/tests/test_proxy.py`
    # or `asyncio.run(unittest.main())` if all tests were async methods of an async test case.
    # For mixed sync/async tests, a runner that supports discovery is best.
    unittest.main()
