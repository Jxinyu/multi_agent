from typing import List


class Solution:
    def groupAnagrams(self, nums: List[int]) -> int:
        nums = set(nums)
        st = 0
        for i in nums:
            if i - 1 in nums:  # i 不是起点
                continue
            s = i  # i 是起点
            index = 1
            while s in nums:  # 找到 i 的终点
                index += 1
                s += 1
            st = max(st, index - 1)
        return st


if __name__ == '__main__':
    print(Solution().groupAnagrams([1, 0, 1, 2]))















