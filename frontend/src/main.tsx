import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#126b57',
          colorInfo: '#126b57',
          colorText: '#17231f',
          colorTextSecondary: '#6f7d77',
          colorBorder: '#d8e0da',
          borderRadius: 8,
          controlHeight: 40,
          fontFamily:
            "'Noto Sans SC', 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif",
        },
        components: {
          Button: { fontWeight: 600 },
          Modal: { titleFontSize: 19 },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
