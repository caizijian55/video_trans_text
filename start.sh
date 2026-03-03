#!/bin/bash
streamlit run app.py --server.address 0.0.0.0 &
sleep 2
my_ip=$(ifconfig | grep -m1 "inet 192" | awk "{print \$2}")
echo "========================================"
echo "✅ 你的真实本地地址（电脑自己用）："
echo "   http://localhost:8501"
echo ""
echo "✅ 你的真实局域网地址（手机/平板用）："
echo "   http://$my_ip:8501"
echo "========================================"
wait
