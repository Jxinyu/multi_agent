import collections
from typing import List


class Solution:
    def maxSlidingWindow(self, nums: List[int], k: int):
        index = k - 1
        res = []
        d = {i: 0 for i in range(len(nums))}
        t = max(nums[:k])
        res.append(t)
        d[index] = t
        index += 1
        while index < len(nums):
            t = nums[index]  # 当前的值
            l = list(d.values())[index - k + 1:index + 1]
            if not l:
                d_max = t
            else:
                l.append(t)
                d_max = max(l)
            res.append(d_max)
            d[index] = d_max
            index += 1
        return res


if __name__ == '__main__':
    print(Solution().maxSlidingWindow([7, 2, 4], 2))
